#!/usr/bin/env python

import argparse
import sqlite3
import sys
import numpy as np
import pandas as pd
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
import joblib

def parse_arguments():
    parser = argparse.ArgumentParser(description="Create TF-IDF and logistic regression models for Eusebius passages")
    parser.add_argument("--database", default="eusebius.sqlite", 
                        help="SQLite database file (default: eusebius.sqlite)")
    parser.add_argument("--min-samples", type=int, default=20,
                        help="Minimum number of samples required to build models (default: 20)")
    parser.add_argument("--test-size", type=float, default=0.2,
                        help="Proportion of data to use for testing (default: 0.2)")
    parser.add_argument("--max-features", type=int, default=1000,
                        help="Maximum number of features for TF-IDF vectorizer (default: 1000)")
    parser.add_argument("--ngram-range", type=str, default="1,2",
                        help="N-gram range for TF-IDF vectorizer, format: min,max (default: 1,2)")
    parser.add_argument("--top-features", type=int, default=30,
                        help="Number of top predictive features to report (default: 30)")
    parser.add_argument("--save-models", action="store_true", default=False,
                        help="Save trained models to disk")
    
    return parser.parse_args()

def create_predictor_tables(conn):
    """Create tables for storing predictive words/phrases."""
    # Table for mythicness predictors
    conn.execute('''
    CREATE TABLE IF NOT EXISTS mythicness_predictors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phrase TEXT NOT NULL,
        coefficient REAL NOT NULL,
        is_mythic INTEGER NOT NULL,
        timestamp TEXT NOT NULL
    )
    ''')
    
    # Table for skepticism predictors
    conn.execute('''
    CREATE TABLE IF NOT EXISTS skepticism_predictors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phrase TEXT NOT NULL,
        coefficient REAL NOT NULL,
        is_skeptical INTEGER NOT NULL,
        timestamp TEXT NOT NULL
    )
    ''')
    
    conn.commit()

def clear_predictor_tables(conn):
    """Clear existing predictor tables before inserting new values."""
    conn.execute("DELETE FROM mythicness_predictors")
    conn.execute("DELETE FROM skepticism_predictors")
    conn.commit()
    print("Cleared existing predictor tables.")

def get_analyzed_passages(conn):
    """Get passages that have been analyzed for both proper nouns and mythicness/skepticism."""
    query = """
    SELECT p.id, p.passage, p.references_mythic_era, p.expresses_scepticism
    FROM passages p
    JOIN noun_extraction_status n ON p.id = n.passage_id
    WHERE p.references_mythic_era IS NOT NULL
    AND p.expresses_scepticism IS NOT NULL
    """
    
    df = pd.read_sql_query(query, conn)
    return df

def get_proper_nouns(conn):
    """Get all proper nouns to use as stopwords."""
    query = """
    SELECT DISTINCT exact_form
    FROM proper_nouns
    """
    
    df = pd.read_sql_query(query, conn)
    return df['exact_form'].tolist()

def save_predictors(conn, feature_names, coefficients, label, table_name):
    """Save predictive features to the database."""
    timestamp = datetime.now().isoformat()
    cursor = conn.cursor()
    
    for feature, coef in zip(feature_names, coefficients):
        is_positive = 1 if coef > 0 else 0
        
        cursor.execute(
            f"""
            INSERT INTO {table_name} (phrase, coefficient, is_{label}, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (feature, float(coef), is_positive, timestamp)
        )
    
    conn.commit()

def build_and_evaluate_model(X, y, vectorizer_params, model_params, feature_label, conn, table_name, top_n=30):
    """Build a TF-IDF + LogReg model, evaluate it, and save top predictors."""
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=args.test_size, random_state=42)
    
    # Create pipeline
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(**vectorizer_params)),
        ('logreg', LogisticRegression(**model_params))
    ])
    
    # Train model
    pipeline.fit(X_train, y_train)
    
    # Evaluate model
    y_pred = pipeline.predict(X_test)
    print(f"\n=== {feature_label.capitalize()} Model Evaluation ===")
    print(classification_report(y_test, y_pred))
    
    # Get feature names and coefficients
    vectorizer = pipeline.named_steps['tfidf']
    model = pipeline.named_steps['logreg']
    
    feature_names = vectorizer.get_feature_names_out()
    coefficients = model.coef_[0]
    
    # Get top positive and negative predictors
    sorted_indices = np.argsort(coefficients)
    top_negative_indices = sorted_indices[:top_n]
    top_positive_indices = sorted_indices[-top_n:]
    
    top_negative_features = [(feature_names[i], coefficients[i]) for i in top_negative_indices]
    top_positive_features = [(feature_names[i], coefficients[i]) for i in top_positive_indices]
    
    # Print top predictors
    print(f"\nTop predictors for NOT {feature_label}:")
    for feature, coef in top_negative_features:
        print(f"  {feature}: {coef:.4f}")
    
    print(f"\nTop predictors for {feature_label}:")
    for feature, coef in top_positive_features:
        print(f"  {feature}: {coef:.4f}")
    
    # Save predictors to database
    all_feature_names = [feature_names[i] for i in np.concatenate([top_negative_indices, top_positive_indices])]
    all_coefficients = [coefficients[i] for i in np.concatenate([top_negative_indices, top_positive_indices])]
    save_predictors(conn, all_feature_names, all_coefficients, feature_label, table_name)
    
    return pipeline

if __name__ == '__main__':
    args = parse_arguments()
    
    # Parse ngram_range
    ngram_min, ngram_max = map(int, args.ngram_range.split(','))
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Create predictor tables if they don't exist
        create_predictor_tables(conn)
        
        # Clear existing predictor data
        clear_predictor_tables(conn)
        
        # Get analyzed passages
        passages_df = get_analyzed_passages(conn)
        
        if len(passages_df) < args.min_samples:
            print(f"Not enough analyzed passages. Found {len(passages_df)}, need at least {args.min_samples}.")
            sys.exit(0)
        
        print(f"Found {len(passages_df)} analyzed passages.")
        print(f"References mythic era: {passages_df['references_mythic_era'].sum()} passages")
        print(f"Expresses skepticism: {passages_df['expresses_scepticism'].sum()} passages")
        
        # Get proper nouns for stopwords
        proper_nouns = get_proper_nouns(conn)
        print(f"Using {len(proper_nouns)} proper nouns as stopwords for mythicness model.")
        
        # Build mythicness model (with proper nouns as stopwords)
        mythic_vectorizer_params = {
            'max_features': args.max_features,
            'ngram_range': (ngram_min, ngram_max),
            'stop_words': proper_nouns
        }
        
        mythic_model_params = {
            'C': 1.0,
            'max_iter': 1000,
            'class_weight': 'balanced',
            'random_state': 42
        }
        
        print("\nBuilding mythicness prediction model...")
        mythic_model = build_and_evaluate_model(
            passages_df['passage'], 
            passages_df['references_mythic_era'],
            mythic_vectorizer_params,
            mythic_model_params,
            'mythic',
            conn,
            'mythicness_predictors',
            args.top_features
        )
        
        # Build skepticism model (without proper noun stopwords)
        skeptic_vectorizer_params = {
            'max_features': args.max_features,
            'ngram_range': (ngram_min, ngram_max),
            'stop_words': []  # No stopwords as requested
        }
        
        skeptic_model_params = {
            'C': 1.0,
            'max_iter': 1000,
            'class_weight': 'balanced',
            'random_state': 42
        }
        
        print("\nBuilding skepticism prediction model...")
        skeptic_model = build_and_evaluate_model(
            passages_df['passage'], 
            passages_df['expresses_scepticism'],
            skeptic_vectorizer_params,
            skeptic_model_params,
            'skeptical',
            conn,
            'skepticism_predictors',
            args.top_features
        )
        
        # Save models if requested
        if args.save_models:
            joblib.dump(mythic_model, 'mythicness_model.joblib')
            joblib.dump(skeptic_model, 'skepticism_model.joblib')
            print("\nModels saved to disk.")
        
        print("\nProcessing complete.")
    
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)
    
    finally:
        conn.close()

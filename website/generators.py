"""HTML page generator functions."""

import os
import html
import pandas as pd
from datetime import datetime
from .highlighting import highlight_passage

def generate_home_page(output_dir, title, timestamp):
    """Generate the home page with build timestamp and links to other pages."""
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <link rel="stylesheet" href="css/style.css">
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            <p>Analysis of Eusebius' Description of Greece</p>
        </header>
        
        <nav>
            <a href="index.html" class="active">Home</a>
            <a href="mythic.html">Mythic Analysis</a>
            <a href="skepticism.html">Skepticism Analysis</a>
            <a href="mythic_words.html">Mythic Words</a>
            <a href="skeptic_words.html">Skeptic Words</a>
            <a href="network_viz/index.html">Network Analysis</a>
        </nav>
        
        <div class="container">
            <h2>Welcome to the Eusebius Analysis Project</h2>
            
            <p>This site presents an analysis of Eusebius' "Description of Greece", focusing on two key aspects:</p>
            
            <div class="home-card">
                <h2>Mythic vs. Historical Content</h2>
                <p>Explore passages with mythical content highlighted in warm colors and italics, 
                   while historical content appears in cool colors.</p>
                <a href="mythic.html">View Mythic Analysis</a>
            </div>
            
            <div class="home-card">
                <h2>Expression of Skepticism</h2>
                <p>Discover how Eusebius expresses skepticism (or credulity) through his writing. 
                   Skeptical content is highlighted in green, while non-skeptical appears in orange and bold.</p>
                <a href="skepticism.html">View Skepticism Analysis</a>
            </div>
            
            <div class="home-card">
                <h2>Predictive Words and Phrases</h2>
                <p>Examine the specific words and phrases that are most strongly associated with mythic content and skepticism.</p>
                <a href="mythic_words.html">Mythic Predictors</a>
                <a href="skeptic_words.html">Skepticism Predictors</a>
            </div>
            
            <footer>
                Site last updated on {timestamp}
            </footer>
        </div>
    </body>
    </html>
    """
    
    # Write the file
    with open(os.path.join(output_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

def generate_mythic_page(passages_df, mythic_color_map, mythic_class_map, proper_nouns_dict, output_dir, title):
    """Generate the page showing mythic aspects of passages."""
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Mythic Analysis</title>
        <link rel="stylesheet" href="css/style.css">
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            <p>Analysis of Mythic vs. Historical Elements in Eusebius</p>
        </header>
        
        <nav>
            <a href="index.html">Home</a>
            <a href="mythic.html" class="active">Mythic Analysis</a>
            <a href="skepticism.html">Skepticism Analysis</a>
            <a href="mythic_words.html">Mythic Words</a>
            <a href="skeptic_words.html">Skeptic Words</a>
            <a href="network_viz/index.html">Network Analysis</a>
        </nav>
        
        <div class="container">
            <div class="legend">
                <h3>Legend:</h3>
                <div class="legend-item">
                    <span class="color-sample mythic-sample"></span> Mythic content (warmer colors, <span class="mythic">italics</span>)
                </div>
                <div class="legend-item">
                    <span class="color-sample historical-sample"></span> Historical content (cooler colors)
                </div>
                <p>Color intensity indicates the strength of the predictive word or phrase.</p>
            </div>
            
            <h2>Passages</h2>
    """
    
    # Add each passage with highlighting
    for _, row in passages_df.iterrows():
        passage_id = row['id']
        passage_text = row['passage']
        is_mythic = row['references_mythic_era']
        translation = row.get('english_translation', None)
        proper_nouns = proper_nouns_dict.get(passage_id, [])
        
        highlighted_passage = highlight_passage(
            passage_text, 
            mythic_color_map, 
            mythic_color_map, 
            mythic_class_map,
            is_mythic_page=True
        )
        
        html_content += f"""
            <div class="passage">
                <div class="passage-header">
                    <span class="passage-id">Passage {passage_id}</span>
                    <span class="passage-class">Class: {'Mythic' if is_mythic else 'Historical'}</span>
                </div>
                <div class="passage-container">
                     <div class="greek-text">
                         {highlighted_passage}
        """

        if proper_nouns:
            html_content += f"""
                        <div class="proper-nouns">
                            <div class="proper-noun-header">Proper Nouns:</div>
            """
            
            for noun in sorted(proper_nouns):
                html_content += f"""
                            <span class="proper-noun-tag">{html.escape(noun)}</span>
                """
            
            html_content += """
                        </div>
            """

        html_content += """
                     </div>
        """

        if translation and not pd.isna(translation):
            html_content += f"""
                    <div class="english-translation">
                        {translation}
                    </div>
            """

    html_content += """
                </div>
            </div>
        """
    
    # Close the HTML
    html_content += """
            <footer>
                Generated on """ + datetime.now().strftime("%Y-%m-%d at %H:%M:%S") + """
            </footer>
        </div>
    </body>
    </html>
    """
    
    # Write the file
    with open(os.path.join(output_dir, 'mythic.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

def generate_skepticism_page(passages_df, skeptic_color_map, skeptic_class_map, proper_nouns_dict, output_dir, title):
    """Generate the page showing skeptical aspects of passages."""
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Skepticism Analysis</title>
        <link rel="stylesheet" href="css/style.css">
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            <p>Analysis of Skepticism in Eusebius</p>
        </header>
        
        <nav>
            <a href="index.html">Home</a>
            <a href="mythic.html">Mythic Analysis</a>
            <a href="skepticism.html" class="active">Skepticism Analysis</a>
            <a href="mythic_words.html">Mythic Words</a>
            <a href="skeptic_words.html">Skeptic Words</a>
            <a href="network_viz/index.html">Network Analysis</a>
        </nav>
        
        <div class="container">
            <div class="legend">
                <h3>Legend:</h3>
                <div class="legend-item">
                    <span class="color-sample skeptical-sample"></span> Skeptical content (green)
                </div>
                <div class="legend-item">
                    <span class="color-sample non-skeptical-sample"></span> Non-skeptical content (orange, <strong>bold</strong>)
                </div>
                <p>Color intensity indicates the strength of the predictive word or phrase.</p>
            </div>
            
            <h2>Passages</h2>
    """
    
    # Add each passage with highlighting
    for _, row in passages_df.iterrows():
        passage_id = row['id']
        passage_text = row['passage']
        is_skeptical = row['expresses_scepticism']
        translation = row.get('english_translation', None)
        proper_nouns = proper_nouns_dict.get(passage_id, [])
        
        highlighted_passage = highlight_passage(
            passage_text, 
            skeptic_color_map, 
            skeptic_color_map, 
            skeptic_class_map,
            is_mythic_page=False
        )
        
        html_content += f"""
            <div class="passage">
                <div class="passage-header">
                    <span class="passage-id">Passage {passage_id}</span>
                    <span class="passage-class">Class: {'Skeptical' if is_skeptical else 'Non-skeptical'}</span>
                </div>
                <div class="passage-container">
                   <div class="greek-text">
                    {highlighted_passage}
        """

        if proper_nouns:
            html_content += f"""
                        <div class="proper-nouns">
                            <div class="proper-noun-header">Proper Nouns:</div>
            """
            
            for noun in sorted(proper_nouns):
                html_content += f"""
                            <span class="proper-noun-tag">{html.escape(noun)}</span>
                """
            
            html_content += """
                        </div>
            """
        html_content += """
                   </div>
        """

        if translation and not pd.isna(translation):
            html_content += f"""
                    <div class="english-translation">
                        {translation}
                    </div>
            """

        html_content += """
            </div>
        </div>
        """
    
    # Close the HTML
    html_content += """
            <footer>
                Generated on """ + datetime.now().strftime("%Y-%m-%d at %H:%M:%S") + """
            </footer>
        </div>
    </body>
    </html>
    """
    
    # Write the file
    with open(os.path.join(output_dir, 'skepticism.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

def generate_mythic_words_page(mythic_predictors, output_dir, title):
    """Generate a page showing words and phrases that predict mythic/historical content."""
    
    # Split into mythic and historical predictors
    mythic_words = mythic_predictors[mythic_predictors['is_mythic'] == 1].sort_values('coefficient', ascending=False)
    historical_words = mythic_predictors[mythic_predictors['is_mythic'] == 0].sort_values('coefficient', ascending=True)
    
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Mythic Predictors</title>
        <link rel="stylesheet" href="css/style.css">
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            <p>Words and Phrases that Predict Mythic vs. Historical Content</p>
        </header>
        
        <nav>
            <a href="index.html">Home</a>
            <a href="mythic.html">Mythic Analysis</a>
            <a href="skepticism.html">Skepticism Analysis</a>
            <a href="mythic_words.html" class="active">Mythic Words</a>
            <a href="skeptic_words.html">Skeptic Words</a>
            <a href="network_viz/index.html">Network Analysis</a>
        </nav>
        
        <div class="container">
            <h2>Predictors of Mythic Content</h2>
            <p>These words and phrases are most strongly associated with mythic content in Eusebius.</p>
            
            <table class="predictor-table">
                <thead>
                    <tr>
                        <th>Word/Phrase</th>
                        <th>Coefficient</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Add mythic predictors
    for _, row in mythic_words.iterrows():
        html_content += f"""
                    <tr>
                        <td class="mythic-word">{html.escape(row['phrase'])}</td>
                        <td>{row['coefficient']:.4f}</td>
                    </tr>
        """
    
    html_content += """
                </tbody>
            </table>
            
            <h2>Predictors of Historical Content</h2>
            <p>These words and phrases are most strongly associated with historical content in Eusebius.</p>
            
            <table class="predictor-table">
                <thead>
                    <tr>
                        <th>Word/Phrase</th>
                        <th>Coefficient</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Add historical predictors
    for _, row in historical_words.iterrows():
        html_content += f"""
                    <tr>
                        <td class="historical-word">{html.escape(row['phrase'])}</td>
                        <td>{row['coefficient']:.4f}</td>
                    </tr>
        """
    
    html_content += """
                </tbody>
            </table>
            
            <footer>
                Generated on """ + datetime.now().strftime("%Y-%m-%d at %H:%M:%S") + """
            </footer>
        </div>
    </body>
    </html>
    """
    
    # Write the file
    with open(os.path.join(output_dir, 'mythic_words.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)

def generate_skeptic_words_page(skeptic_predictors, output_dir, title):
    """Generate a page showing words and phrases that predict skeptical/non-skeptical content."""
    
    # Split into skeptical and non-skeptical predictors
    skeptical_words = skeptic_predictors[skeptic_predictors['is_skeptical'] == 1].sort_values('coefficient', ascending=False)
    non_skeptical_words = skeptic_predictors[skeptic_predictors['is_skeptical'] == 0].sort_values('coefficient', ascending=True)
    
    html_content = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - Skepticism Predictors</title>
        <link rel="stylesheet" href="css/style.css">
    </head>
    <body>
        <header>
            <h1>{title}</h1>
            <p>Words and Phrases that Predict Skeptical vs. Non-skeptical Content</p>
        </header>
        
        <nav>
            <a href="index.html">Home</a>
            <a href="mythic.html">Mythic Analysis</a>
            <a href="skepticism.html">Skepticism Analysis</a>
            <a href="mythic_words.html">Mythic Words</a>
            <a href="skeptic_words.html" class="active">Skeptic Words</a>
            <a href="network_viz/index.html">Network Analysis</a>
        </nav>
        
        <div class="container">
            <h2>Predictors of Skeptical Content</h2>
            <p>These words and phrases are most strongly associated with skeptical content in Eusebius.</p>
            
            <table class="predictor-table">
                <thead>
                    <tr>
                        <th>Word/Phrase</th>
                        <th>Coefficient</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Add skeptical predictors
    for _, row in skeptical_words.iterrows():
        html_content += f"""
                    <tr>
                        <td class="skeptical-word">{html.escape(row['phrase'])}</td>
                        <td>{row['coefficient']:.4f}</td>
                    </tr>
        """
    
    html_content += """
                </tbody>
            </table>
            
            <h2>Predictors of Non-skeptical Content</h2>
            <p>These words and phrases are most strongly associated with non-skeptical content in Eusebius.</p>
            
            <table class="predictor-table">
                <thead>
                    <tr>
                        <th>Word/Phrase</th>
                        <th>Coefficient</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    # Add non-skeptical predictors
    for _, row in non_skeptical_words.iterrows():
        html_content += f"""
                    <tr>
                        <td class="non-skeptical-word">{html.escape(row['phrase'])}</td>
                        <td>{row['coefficient']:.4f}</td>
                    </tr>
        """
    
    html_content += """
                </tbody>
            </table>
            
            <footer>
                Generated on """ + datetime.now().strftime("%Y-%m-%d at %H:%M:%S") + """
            </footer>
        </div>
    </body>
    </html>
    """
    
    # Write the file
    with open(os.path.join(output_dir, 'skeptic_words.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)
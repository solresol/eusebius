#!/usr/bin/env python

import argparse
import sqlite3
import sys
import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
from datetime import datetime
from collections import defaultdict
import json

def parse_arguments():
    parser = argparse.ArgumentParser(description="Analyze the network of proper nouns in Eusebius")
    parser.add_argument("--database", default="eusebius.sqlite", 
                        help="SQLite database file (default: eusebius.sqlite)")
    parser.add_argument("--min-cooccurrence", type=int, default=1,
                        help="Minimum number of co-occurrences for an edge (default: 1)")
    parser.add_argument("--top-nodes", type=int, default=100,
                        help="Number of top nodes to include in visualization (default: 100)")
    parser.add_argument("--output-dir", default="eusebius_site/network_viz",
                        help="Output directory for network visualizations (default: eusebius_site/network_viz)")
    
    return parser.parse_args()

def passage_id_sort_key(passage_id):
    """Create a sort key for passage IDs in the format X.Y.Z."""
    parts = passage_id.split('.')
    # Convert each part to integer for proper numerical sorting
    return tuple(int(part) for part in parts)

def create_centrality_table(conn):
    """Create the table for storing centrality measures if it doesn't exist."""
    conn.execute('''
    CREATE TABLE IF NOT EXISTS noun_centrality (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reference_form TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        english_transcription TEXT NOT NULL,
        component_id INTEGER NOT NULL,
        degree_centrality REAL,
        betweenness_centrality REAL,
        eigenvector_centrality REAL,
        pagerank REAL,
        clustering_coefficient REAL,
        timestamp TEXT NOT NULL,
        UNIQUE(reference_form, entity_type, component_id)
    )
    ''')
    conn.commit()

def clear_centrality_table(conn):
    """Clear existing centrality data before inserting new values."""
    conn.execute("DELETE FROM noun_centrality")
    conn.commit()
    print("Cleared existing centrality data.")

def get_noun_nodes(conn):
    """Get all distinct proper nouns as nodes."""
    query = """
    SELECT reference_form, entity_type, english_transcription
    FROM proper_nouns
    GROUP BY reference_form, entity_type
    """
    
    df = pd.read_sql_query(query, conn)
    return df

def get_cooccurrences(conn):
    """Get all passage IDs where each proper noun appears."""
    query = """
    SELECT passage_id, reference_form, entity_type
    FROM proper_nouns
    """
    
    df = pd.read_sql_query(query, conn)
    return df

def build_graph(nodes_df, cooccurrences_df, min_cooccurrence=1):
    """Build a network graph where nodes are proper nouns and edges represent co-occurrences."""
    # Create a graph
    G = nx.Graph()
    
    # Add nodes with attributes
    for _, row in nodes_df.iterrows():
        G.add_node(
            (row['reference_form'], row['entity_type']),
            reference_form=row['reference_form'],
            entity_type=row['entity_type'],
            english_transcription=row['english_transcription']
        )
    
    # Group by passage_id to find co-occurrences
    passage_nouns = defaultdict(list)
    for _, row in cooccurrences_df.iterrows():
        passage_nouns[row['passage_id']].append(
            (row['reference_form'], row['entity_type'])
        )
    
    # Add edges for co-occurrences
    edge_weights = defaultdict(int)
    for passage_id, nouns in passage_nouns.items():
        for i, noun1 in enumerate(nouns):
            for noun2 in nouns[i+1:]:
                # Skip self-connections
                if noun1 == noun2:
                    continue
                    
                # Ensure the order is consistent
                if noun1 < noun2:
                    edge = (noun1, noun2)
                else:
                    edge = (noun2, noun1)
                edge_weights[edge] += 1
    
    # Add edges with weights to the graph
    for edge, weight in edge_weights.items():
        if weight >= min_cooccurrence:
            G.add_edge(edge[0], edge[1], weight=weight)
    
    print(f"Built graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges.")
    return G

def get_connected_components(G):
    """Break the graph into connected components and assign component IDs."""
    components = list(nx.connected_components(G))
    print(f"Found {len(components)} connected components.")
    
    # Create a mapping from node to component ID
    node_to_component = {}
    for i, component in enumerate(components):
        for node in component:
            node_to_component[node] = i
    
    # Create subgraphs for each component
    component_graphs = []
    for i, component in enumerate(components):
        subgraph = G.subgraph(component).copy()
        print(f"Component {i}: {subgraph.number_of_nodes()} nodes, {subgraph.number_of_edges()} edges")
        component_graphs.append((i, subgraph))
    
    return component_graphs, node_to_component

def calculate_centrality_measures(G, component_id):
    """Calculate various centrality measures for a connected component."""
    print(f"Calculating centrality measures for component {component_id}...")
    
    # Skip tiny components (1-2 nodes) for some measures
    if G.number_of_nodes() <= 2:
        degree_centrality = nx.degree_centrality(G)
        betweenness_centrality = {node: 0.0 for node in G.nodes()}
        if G.number_of_nodes() == 1:
            # For single node, set eigenvector centrality and pagerank to 1.0
            eigenvector_centrality = {node: 1.0 for node in G.nodes()}
            pagerank = {node: 1.0 for node in G.nodes()}
        else:
            # For two nodes, calculate basic measures
            eigenvector_centrality = {node: 0.5 for node in G.nodes()}
            pagerank = {node: 0.5 for node in G.nodes()}
            
        clustering_coefficient = {node: 0.0 for node in G.nodes()}
    else:
        print("  Calculating degree centrality...")
        degree_centrality = nx.degree_centrality(G)
        
        print("  Calculating betweenness centrality...")
        betweenness_centrality = nx.betweenness_centrality(G, weight='weight')
        
        print("  Calculating eigenvector centrality...")
        try:
            eigenvector_centrality = nx.eigenvector_centrality_numpy(G, weight='weight')
        except nx.NetworkXError:
            print("  Warning: Eigenvector centrality calculation failed. Using power iteration method.")
            try:
                eigenvector_centrality = nx.eigenvector_centrality(G, weight='weight', max_iter=1000)
            except nx.PowerIterationFailedConvergence:
                print("  Warning: Power iteration failed to converge. Using degree centrality as fallback.")
                eigenvector_centrality = degree_centrality
        
        print("  Calculating PageRank...")
        pagerank = nx.pagerank(G, weight='weight')
        
        print("  Calculating clustering coefficients...")
        clustering_coefficient = nx.clustering(G, weight='weight')
    
    # Combine all centrality measures
    centrality_data = []
    for node in G.nodes():
        centrality_data.append({
            'reference_form': node[0],
            'entity_type': node[1],
            'english_transcription': G.nodes[node]['english_transcription'],
            'component_id': component_id,
            'degree_centrality': degree_centrality[node],
            'betweenness_centrality': betweenness_centrality[node],
            'eigenvector_centrality': eigenvector_centrality[node],
            'pagerank': pagerank[node],
            'clustering_coefficient': clustering_coefficient[node]
        })
    
    return pd.DataFrame(centrality_data)

def save_centrality_measures(conn, centrality_df):
    """Save centrality measures to the database."""
    timestamp = datetime.now().isoformat()
    
    for _, row in centrality_df.iterrows():
        conn.execute(
            """
            INSERT OR REPLACE INTO noun_centrality 
            (reference_form, entity_type, english_transcription, component_id,
             degree_centrality, betweenness_centrality, eigenvector_centrality, 
             pagerank, clustering_coefficient, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row['reference_form'], row['entity_type'], row['english_transcription'],
                row['component_id'], row['degree_centrality'], row['betweenness_centrality'], 
                row['eigenvector_centrality'], row['pagerank'], 
                row['clustering_coefficient'], timestamp
            )
        )
    
    conn.commit()
    print(f"Saved centrality measures for {len(centrality_df)} nodes.")

def create_d3_html_template(output_dir):
    """Create HTML templates for D3 visualizations."""
    # Ensure the directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Create main index.html for network visualization
    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Eusebius Proper Noun Network</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {
            font-family: 'Palatino Linotype', 'Book Antiqua', Palatino, serif;
            margin: 0;
            padding: 0;
            background-color: #f9f8f4;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            background-color: #5c5142;
            color: white;
            padding: 1em;
            text-align: center;
        }
        
        nav {
            background-color: #776b5d;
            padding: 0.5em;
            text-align: center;
        }
        
        nav a {
            color: white;
            margin: 0 15px;
            text-decoration: none;
            font-weight: bold;
        }
        
        nav a:hover {
            text-decoration: underline;
        }
        
        #visualization {
            width: 100%;
            height: 800px;
            border: 1px solid #ddd;
            margin-top: 20px;
            background-color: white;
        }
        
        .legend {
            margin-top: 20px;
            padding: 15px;
            background-color: #eee9e3;
            border-radius: 5px;
        }
        
        .legend-item {
            display: inline-block;
            margin-right: 20px;
            margin-bottom: 10px;
        }
        
        .color-sample {
            display: inline-block;
            width: 20px;
            height: 20px;
            margin-right: 5px;
            vertical-align: middle;
            border-radius: 50%;
        }
        
        .person-sample {
            background-color: blue;
        }
        
        .place-sample {
            background-color: green;
        }
        
        .deity-sample {
            background-color: red;
        }
        
        .other-sample {
            background-color: orange;
        }
        
        .tooltip {
            position: absolute;
            background-color: white;
            padding: 10px;
            border-radius: 5px;
            border: 1px solid #ddd;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
        }
        
        .controls {
            margin-top: 20px;
            padding: 15px;
            background-color: #eee9e3;
            border-radius: 5px;
        }
        
        .controls h3 {
            margin-top: 0;
        }
        
        .controls select, .controls input {
            margin: 5px;
            padding: 5px;
        }
        
        footer {
            text-align: center;
            margin-top: 30px;
            padding: 10px;
            background-color: #eee9e3;
            font-size: 0.8em;
        }
    </style>
</head>
<body>
    <header>
        <h1>Eusebius Proper Noun Network</h1>
        <p>Interactive visualization of proper noun connections in Eusebius' Description of Greece</p>
    </header>
    
    <nav>
        <a href="../index.html">Home</a>
        <a href="../mythic.html">Mythic Analysis</a>
        <a href="../skepticism.html">Skepticism Analysis</a>
        <a href="../mythic_words.html">Mythic Words</a>
        <a href="../skeptic_words.html">Skeptic Words</a>
        <a href="index.html" class="active">Network Analysis</a>
    </nav>
    
    <div class="container">
        <div class="controls">
            <h3>Visualization Controls</h3>
            <div>
                <label for="component-select">Component: </label>
                <select id="component-select">
                    <!-- <option value="all">Full Network</option> -->
                    <!-- Component options will be added dynamically -->
                </select>
            </div>
            <div>
                <label for="centrality-type">Size by: </label>
                <select id="centrality-type">
                    <option value="degree">Degree Centrality</option>
                    <option value="betweenness">Betweenness Centrality</option>
                    <option value="eigenvector">Eigenvector Centrality</option>
                    <option value="pagerank">PageRank</option>
                </select>
            </div>
            <div>
                <label for="min-links">Minimum Links: </label>
                <input type="range" id="min-links" min="1" max="10" value="1">
                <span id="min-links-value">1</span>
            </div>
            <div>
                <label for="node-limit">Max Nodes: </label>
                <input type="range" id="node-limit" min="20" max="1000" value="250" step="10">
                <span id="node-limit-value">250</span>
            </div>
        </div>
        
        <div class="legend">
            <h3>Legend:</h3>
            <div class="legend-item">
                <span class="color-sample person-sample"></span> Person
            </div>
            <div class="legend-item">
                <span class="color-sample place-sample"></span> Place
            </div>
            <div class="legend-item">
                <span class="color-sample deity-sample"></span> Deity
            </div>
            <div class="legend-item">
                <span class="color-sample other-sample"></span> Other
            </div>
            <p>Larger nodes have higher centrality values. Thicker connections represent more frequent co-occurrences.</p>
        </div>
        
        <div id="loading-spinner" style="text-align:center; padding:20px;">Loading network data…</div>
        <div id="visualization" style="display:none;"></div>
        
        <div id="tooltip" class="tooltip"></div>
        
        <footer>
            Generated on <span id="timestamp"></span>
        </footer>
    </div>
    
    <script>
        // Load the network data
        d3.json('network_data.json').then(data => {
            document.getElementById('loading-spinner').style.display = 'none';
            document.getElementById('visualization').style.display = 'block';
            const timestamp = new Date().toISOString();
            document.getElementById('timestamp').textContent = new Date().toLocaleString();
            
            // Setup the visualization
            const width = document.getElementById('visualization').clientWidth;
            const height = document.getElementById('visualization').clientHeight;
            
            // Create the SVG
            const svg = d3.select('#visualization')
                .append('svg')
                .attr('width', width)
                .attr('height', height);
            
            // Create a group for all elements
            const g = svg.append('g');
            
            // Add zoom behavior
            const zoom = d3.zoom()
                .scaleExtent([0.1, 8])
                .on('zoom', (event) => {
                    g.attr('transform', event.transform);
                });
            
            svg.call(zoom);
            
            // Setup color scale for entity types
            const colorScale = d3.scaleOrdinal()
                .domain(['person', 'place', 'deity', 'other'])
                .range(['blue', 'green', 'red', 'orange']);
            
            // Populate component select
            const componentSelect = document.getElementById('component-select');
            data.components.sort((a, b) => b.size - a.size).forEach(comp => {
                const option = document.createElement('option');
                option.value = comp.id;
                option.textContent = `Component ${comp.id} (${comp.size} nodes)`;
                componentSelect.appendChild(option);
            });
            
            // Create force simulation
            let simulation = d3.forceSimulation()
                .force('link', d3.forceLink().id(d => d.id).distance(80).strength(0.7))
                .force('charge', d3.forceManyBody()
                    .strength(-100)
                    .distanceMax(800)
                    .theta(0.8))
                .force('center', d3.forceCenter(width / 2, height / 2))
                .force('x', d3.forceX(width / 2).strength(0.05))  // Added gentle x-centering force
                .force('y', d3.forceY(height / 2).strength(0.05))  // Added gentle y-centering force
                .force('collision', d3.forceCollide().radius(d => d.radius || 10));
            
            // Create tooltip
            const tooltip = d3.select('#tooltip');

            function getId(val) {
                return typeof val === 'object' ? val.id : val;
            }

            // Function to update the visualization

            function updateVisualization() {
                // Get filter values
                const selectedComponent = componentSelect.value;
                const centralityType = document.getElementById('centrality-type').value;
                const minLinks = parseInt(document.getElementById('min-links').value);
                const nodeLimit = parseInt(document.getElementById('node-limit').value);
                
                // Filter nodes and links
                let filteredNodes, filteredLinks;
                
                if (selectedComponent === 'all') {
                    // For full network, get the largest components up to node limit
                    const sortedComponents = [...data.components].sort((a, b) => b.size - a.size);
                    const includedComponents = new Set();
                    let nodeCount = 0;
                    
                    for (const comp of sortedComponents) {
                        if (nodeCount + comp.size <= nodeLimit) {
                            includedComponents.add(comp.id);
                            nodeCount += comp.size;
                        } else {
                            break;
                        }
                    }
                    
                    filteredNodes = data.nodes.filter(n => includedComponents.has(n.component));
                    filteredLinks = data.links.filter(l => {
                        const sourceId = getId(l.source);
                        const targetId = getId(l.target);
                        const sourceNode = data.nodes.find(n => n.id === sourceId);
                        const targetNode = data.nodes.find(n => n.id === targetId);
                        return sourceNode && targetNode &&
                               includedComponents.has(sourceNode.component) &&
                               includedComponents.has(targetNode.component) &&
                               l.weight >= minLinks;
                    });
                } else {
                    // For a specific component
                    const compId = parseInt(selectedComponent);
                    filteredNodes = data.nodes.filter(n => n.component === compId)
                        .slice(0, nodeLimit);
                    
                    const nodeIds = new Set(filteredNodes.map(n => n.id));
                    filteredLinks = data.links.filter(l =>
                        nodeIds.has(getId(l.source)) && nodeIds.has(getId(l.target)) && l.weight >= minLinks
                    );
                }
                
                // Get centrality values for sizing nodes
                let centralityValues = [];
                if (centralityType === 'degree') {
                    // Calculate degree from links
                    const degreeCount = {};
                    filteredLinks.forEach(l => {
                        const s = getId(l.source);
                        const t = getId(l.target);
                        degreeCount[s] = (degreeCount[s] || 0) + 1;
                        degreeCount[t] = (degreeCount[t] || 0) + 1;
                    });
                    centralityValues = filteredNodes.map(n => degreeCount[n.id] || 0);
                } else {
                    // For other centrality measures, use API to fetch values
                    // TODO: Add database connection to get actual centrality values
                    centralityValues = filteredNodes.map(() => Math.random());
                }
                
                // Calculate node sizes based on centrality
                const sizeScale = d3.scaleLinear()
                    .domain([0, d3.max(centralityValues) || 1])
                    .range([5, 25]);
                
                filteredNodes.forEach((node, i) => {
                    node.radius = sizeScale(centralityValues[i]);
                });
                
                // Update the visualization
                
                // Clear existing elements
                g.selectAll('*').remove();
                
                // Create links
                const links = g.selectAll('.link')
                    .data(filteredLinks)
                    .enter()
                    .append('line')
                    .attr('class', 'link')
                    .attr('stroke', '#999')
                    .attr('stroke-opacity', 0.6)
                    .attr('stroke-width', d => Math.sqrt(d.weight));
                
                // Create nodes
                const nodes = g.selectAll('.node')
                    .data(filteredNodes)
                    .enter()
                    .append('circle')
                    .attr('class', 'node')
                    .attr('r', d => d.radius)
                    .attr('fill', d => colorScale(d.entity_type))
                    .attr('stroke', '#fff')
                    .attr('stroke-width', 1.5)
                    .call(d3.drag()
                        .on('start', dragstarted)
                        .on('drag', dragged)
                        .on('end', dragended))
                    .on('mouseover', function(event, d) {
                        tooltip.transition()
                            .duration(200)
                            .style('opacity', .9);
                        tooltip.html(`<strong>${d.english_name}</strong><br>
                                     Type: ${d.entity_type}<br>
                                     Greek: ${d.reference_form}`)
                            .style('left', (event.pageX + 10) + 'px')
                            .style('top', (event.pageY - 28) + 'px');
                    })
                    .on('mouseout', function() {
                        tooltip.transition()
                            .duration(500)
                            .style('opacity', 0);
                    });
                
                // Add labels to the largest nodes
                const topNodes = filteredNodes
                    .sort((a, b) => b.radius - a.radius)
                    .slice(0, 20);
                
                g.selectAll('.node-label')
                    .data(topNodes)
                    .enter()
                    .append('text')
                    .attr('class', 'node-label')
                    .attr('dx', d => d.radius + 3)
                    .attr('dy', '.35em')
                    .text(d => d.english_name)
                    .attr('font-size', 10)
                    .attr('font-weight', 'bold');
                
                // Update simulation
                simulation.nodes(filteredNodes)
                    .force('link').links(filteredLinks);
                
                simulation.alpha(1).restart();
                
                // Position elements on tick
                simulation.on('tick', () => {
                    links
                        .attr('x1', d => d.source.x)
                        .attr('y1', d => d.source.y)
                        .attr('x2', d => d.target.x)
                        .attr('y2', d => d.target.y);
                    
                    nodes
                        .attr('cx', d => d.x = Math.max(d.radius, Math.min(width - d.radius, d.x)))
                        .attr('cy', d => d.y = Math.max(d.radius, Math.min(height - d.radius, d.y)));
                    
                    g.selectAll('.node-label')
                        .attr('x', d => d.x)
                        .attr('y', d => d.y);
                });
            }
            
            // Drag functions
            function dragstarted(event, d) {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            }
            
            function dragged(event, d) {
                d.fx = event.x;
                d.fy = event.y;
            }
            
            function dragended(event, d) {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }
            
            // Initialize the visualization
            updateVisualization();
            
            // Add event listeners for controls
            componentSelect.addEventListener('change', updateVisualization);
            document.getElementById('centrality-type').addEventListener('change', updateVisualization);
            
            const minLinksSlider = document.getElementById('min-links');
            minLinksSlider.addEventListener('input', function() {
                document.getElementById('min-links-value').textContent = this.value;
            });
            minLinksSlider.addEventListener('change', updateVisualization);
            
            const nodeLimitSlider = document.getElementById('node-limit');
            nodeLimitSlider.addEventListener('input', function() {
                document.getElementById('node-limit-value').textContent = this.value;
            });
            nodeLimitSlider.addEventListener('change', updateVisualization);
        }).catch(error => {
            console.error('Error loading network data:', error);
            document.getElementById('visualization').innerHTML = 
                '<div style="padding: 20px; color: red;">Error loading network data. Please check the console for details.</div>';
        });
    </script>
</body>
</html>
"""
    
    # Create component template
    component_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Component {component_id} - Eusebius Proper Noun Network</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {
            font-family: 'Palatino Linotype', 'Book Antiqua', Palatino, serif;
            margin: 0;
            padding: 0;
            background-color: #f9f8f4;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            background-color: #5c5142;
            color: white;
            padding: 1em;
            text-align: center;
        }
        
        nav {
            background-color: #776b5d;
            padding: 0.5em;
            text-align: center;
        }
        
        nav a {
            color: white;
            margin: 0 15px;
            text-decoration: none;
            font-weight: bold;
        }
        
        nav a:hover {
            text-decoration: underline;
        }
        
        #visualization {
            width: 100%;
            height: 800px;
            border: 1px solid #ddd;
            margin-top: 20px;
            background-color: white;
        }
        
        .legend {
            margin-top: 20px;
            padding: 15px;
            background-color: #eee9e3;
            border-radius: 5px;
        }
        
        .legend-item {
            display: inline-block;
            margin-right: 20px;
            margin-bottom: 10px;
        }
        
        .color-sample {
            display: inline-block;
            width: 20px;
            height: 20px;
            margin-right: 5px;
            vertical-align: middle;
            border-radius: 50%;
        }
        
        .person-sample {
            background-color: blue;
        }
        
        .place-sample {
            background-color: green;
        }
        
        .deity-sample {
            background-color: red;
        }
        
        .other-sample {
            background-color: orange;
        }
        
        .tooltip {
            position: absolute;
            background-color: white;
            padding: 10px;
            border-radius: 5px;
            border: 1px solid #ddd;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.2s;
        }
        
        .controls {
            margin-top: 20px;
            padding: 15px;
            background-color: #eee9e3;
            border-radius: 5px;
        }
        
        .controls h3 {
            margin-top: 0;
        }
        
        .controls select, .controls input {
            margin: 5px;
            padding: 5px;
        }
        
        footer {
            text-align: center;
            margin-top: 30px;
            padding: 10px;
            background-color: #eee9e3;
            font-size: 0.8em;
        }
    </style>
</head>
<body>
    <header>
        <h1>Component {component_id} - Eusebius Proper Noun Network</h1>
        <p>Interactive visualization of proper noun connections in component {component_id}</p>
    </header>
    
    <nav>
        <a href="../index.html">Home</a>
        <a href="../mythic.html">Mythic Analysis</a>
        <a href="../skepticism.html">Skepticism Analysis</a>
        <a href="../mythic_words.html">Mythic Words</a>
        <a href="../skeptic_words.html">Skeptic Words</a>
        <a href="index.html">Network Analysis</a>
        <a href="component_{component_id}.html" class="active">Component {component_id}</a>
    </nav>
    
    <div class="container">
        <div class="controls">
            <h3>Visualization Controls</h3>
            <div>
                <label for="centrality-type">Size by: </label>
                <select id="centrality-type">
                    <option value="degree">Degree Centrality</option>
                    <option value="betweenness">Betweenness Centrality</option>
                    <option value="eigenvector">Eigenvector Centrality</option>
                    <option value="pagerank">PageRank</option>
                </select>
            </div>
            <div>
                <label for="min-links">Minimum Links: </label>
                <input type="range" id="min-links" min="1" max="10" value="1">
                <span id="min-links-value">1</span>
            </div>
        </div>
        
        <div class="legend">
            <h3>Legend:</h3>
            <div class="legend-item">
                <span class="color-sample person-sample"></span> Person
            </div>
            <div class="legend-item">
                <span class="color-sample place-sample"></span> Place
            </div>
            <div class="legend-item">
                <span class="color-sample deity-sample"></span> Deity
            </div>
            <div class="legend-item">
                <span class="color-sample other-sample"></span> Other
            </div>
            <p>Larger nodes have higher centrality values. Thicker connections represent more frequent co-occurrences.</p>
        </div>
        
        <div id="loading-spinner" style="text-align:center; padding:20px;">Loading network data…</div>
        <div id="visualization" style="display:none;"></div>
        
        <div id="tooltip" class="tooltip"></div>
        
        <footer>
            Generated on <span id="timestamp"></span>
        </footer>
    </div>
    
    <script>
        // Load the network data
        d3.json('component_{component_id}/network_data.json').then(data => {
            document.getElementById('loading-spinner').style.display = 'none';
            document.getElementById('visualization').style.display = 'block';
            const timestamp = new Date().toISOString();
            document.getElementById('timestamp').textContent = new Date().toLocaleString();
            
            // Setup the visualization
            const width = document.getElementById('visualization').clientWidth;
            const height = document.getElementById('visualization').clientHeight;
            
            // Create the SVG
            const svg = d3.select('#visualization')
                .append('svg')
                .attr('width', width)
                .attr('height', height);
            
            // Create a group for all elements
            const g = svg.append('g');
            
            // Add zoom behavior
            const zoom = d3.zoom()
                .scaleExtent([0.1, 8])
                .on('zoom', (event) => {
                    g.attr('transform', event.transform);
                });
            
            svg.call(zoom);
            
            // Setup color scale for entity types
            const colorScale = d3.scaleOrdinal()
                .domain(['person', 'place', 'deity', 'other'])
                .range(['blue', 'green', 'red', 'orange']);
            
            // Create force simulation
            let simulation = d3.forceSimulation()
                .force('link', d3.forceLink().id(d => d.id).distance(100))
                .force('charge', d3.forceManyBody().strength(-200))
                .force('center', d3.forceCenter(width / 2, height / 2))
                .force('collision', d3.forceCollide().radius(d => d.radius || 10));
            
            // Create tooltip
            const tooltip = d3.select('#tooltip');
            
            // Function to update the visualization
            function updateVisualization() {
                // Get filter values
                const centralityType = document.getElementById('centrality-type').value;
                const minLinks = parseInt(document.getElementById('min-links').value);
                
                // Filter links based on minimum weight
                const filteredLinks = data.links.filter(l => l.weight >= minLinks);

                // Get node IDs that are part of the filtered links
                const connectedNodeIds = new Set();
                filteredLinks.forEach(l => {
                    const s = getId(l.source);
                    const t = getId(l.target);
                    connectedNodeIds.add(s);
                    connectedNodeIds.add(t);
                });
                
                // Filter nodes to include only those in the filtered links
                const filteredNodes = data.nodes.filter(n => connectedNodeIds.has(n.id));
                
                // Get centrality values for sizing nodes
                let centralityValues = [];
                if (centralityType === 'degree') {
                    // Calculate degree from links
                    const degreeCount = {};
                    filteredLinks.forEach(l => {
                        const s = getId(l.source);
                        const t = getId(l.target);
                        degreeCount[s] = (degreeCount[s] || 0) + 1;
                        degreeCount[t] = (degreeCount[t] || 0) + 1;
                    });
                    centralityValues = filteredNodes.map(n => degreeCount[n.id] || 0);
                } else {
                    // For other centrality measures, use API to fetch values
                    // TODO: Add database connection to get actual centrality values
                    centralityValues = filteredNodes.map(() => Math.random());
                }
                
                // Calculate node sizes based on centrality
                const sizeScale = d3.scaleLinear()
                    .domain([0, d3.max(centralityValues) || 1])
                    .range([5, 25]);
                
                filteredNodes.forEach((node, i) => {
                    node.radius = sizeScale(centralityValues[i]);
                });
                
                // Update the visualization
                
                // Clear existing elements
                g.selectAll('*').remove();
                
                // Create links
                const links = g.selectAll('.link')
                    .data(filteredLinks)
                    .enter()
                    .append('line')
                    .attr('class', 'link')
                    .attr('stroke', '#999')
                    .attr('stroke-opacity', 0.6)
                    .attr('stroke-width', d => Math.sqrt(d.weight));
                
                // Create nodes
                const nodes = g.selectAll('.node')
                    .data(filteredNodes)
                    .enter()
                    .append('circle')
                    .attr('class', 'node')
                    .attr('r', d => d.radius)
                    .attr('fill', d => colorScale(d.entity_type))
                    .attr('stroke', '#fff')
                    .attr('stroke-width', 1.5)
                    .call(d3.drag()
                        .on('start', dragstarted)
                        .on('drag', dragged)
                        .on('end', dragended))
                    .on('mouseover', function(event, d) {
                        tooltip.transition()
                            .duration(200)
                            .style('opacity', .9);
                        tooltip.html(`<strong>${d.english_name}</strong><br>
                                     Type: ${d.entity_type}<br>
                                     Greek: ${d.reference_form}`)
                            .style('left', (event.pageX + 10) + 'px')
                            .style('top', (event.pageY - 28) + 'px');
                    })
                    .on('mouseout', function() {
                        tooltip.transition()
                            .duration(500)
                            .style('opacity', 0);
                    });
                
                // Add labels to the largest nodes
                const topNodes = filteredNodes
                    .sort((a, b) => b.radius - a.radius)
                    .slice(0, 20);
                
                g.selectAll('.node-label')
                    .data(topNodes)
                    .enter()
                    .append('text')
                    .attr('class', 'node-label')
                    .attr('dx', d => d.radius + 3)
                    .attr('dy', '.35em')
                    .text(d => d.english_name)
                    .attr('font-size', 10)
                    .attr('font-weight', 'bold');
                
                // Update simulation
                simulation.nodes(filteredNodes)
                    .force('link').links(filteredLinks);
                
                simulation.alpha(1).restart();
                
                // Position elements on tick
                simulation.on('tick', () => {
                    links
                        .attr('x1', d => d.source.x)
                        .attr('y1', d => d.source.y)
                        .attr('x2', d => d.target.x)
                        .attr('y2', d => d.target.y);
                    
                    nodes
                        .attr('cx', d => d.x = Math.max(d.radius, Math.min(width - d.radius, d.x)))
                        .attr('cy', d => d.y = Math.max(d.radius, Math.min(height - d.radius, d.y)));
                    
                    g.selectAll('.node-label')
                        .attr('x', d => d.x)
                        .attr('y', d => d.y);
                });
            }
            
            // Drag functions
            function dragstarted(event, d) {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            }
            
            function dragged(event, d) {
                d.fx = event.x;
                d.fy = event.y;
            }
            
            function dragended(event, d) {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }
            
            // Initialize the visualization
            updateVisualization();
            
            // Add event listeners for controls
            document.getElementById('centrality-type').addEventListener('change', updateVisualization);
            
            const minLinksSlider = document.getElementById('min-links');
            minLinksSlider.addEventListener('input', function() {
                document.getElementById('min-links-value').textContent = this.value;
            });
            minLinksSlider.addEventListener('change', updateVisualization);
        }).catch(error => {
            console.error('Error loading network data:', error);
            document.getElementById('visualization').innerHTML = 
                '<div style="padding: 20px; color: red;">Error loading network data. Please check the console for details.</div>';
        });
    </script>
</body>
</html>
"""
    
    with open(os.path.join(output_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)
    
    print(f"Created D3 HTML templates in {output_dir}")
    
    return index_html, component_html

def visualize_component(G, component_id, centrality_df, output_dir, top_n=100):
    """Visualize a network component highlighting the most central nodes."""
    # Create component subdirectory
    component_dir = os.path.join(output_dir, f"component_{component_id}")
    os.makedirs(component_dir, exist_ok=True)
    
    # Filter centrality dataframe for this component
    component_df = centrality_df[centrality_df['component_id'] == component_id]
    
    # Skip visualization for very small components
    if len(component_df) <= 2:
        print(f"Skipping visualization for component {component_id} (too small).")
        return
    
    # Limit to top_n nodes if the component is larger
    if len(component_df) > top_n:
        # Get top nodes by different centrality measures
        top_by_degree = component_df.nlargest(top_n, 'degree_centrality')
        top_by_betweenness = component_df.nlargest(top_n, 'betweenness_centrality')
        top_by_eigenvector = component_df.nlargest(top_n, 'eigenvector_centrality')
        top_by_pagerank = component_df.nlargest(top_n, 'pagerank')
        
        # Create subgraphs for visualization
        measures = {
            'degree': top_by_degree,
            'betweenness': top_by_betweenness,
            'eigenvector': top_by_eigenvector,
            'pagerank': top_by_pagerank
        }
    else:
        # For smaller components, just use the whole component for all measures
        measures = {
            'degree': component_df,
            'betweenness': component_df,
            'eigenvector': component_df,
            'pagerank': component_df
        }
    
    # Define colors for entity types
    entity_colors = {
        'person': 'blue',
        'place': 'green',
        'deity': 'red',
        'other': 'orange'
    }
    
    # Generate visualizations for each centrality measure
    for measure_name, measure_df in measures.items():
        plt.figure(figsize=(14, 14))
        
        # Create subgraph with selected nodes
        node_set = [(row['reference_form'], row['entity_type']) for _, row in measure_df.iterrows()]
        subgraph = nx.subgraph(G, node_set)
        
        # Use spring layout for visualization
        pos = nx.spring_layout(subgraph, seed=42, k=0.5, iterations=100)
        
        # Get node sizes based on centrality measure
        if measure_name == 'degree':
            node_sizes = [component_df.loc[component_df['reference_form'] == subgraph.nodes[node]['reference_form']].iloc[0]['degree_centrality'] * 5000 + 100 for node in subgraph.nodes()]
        elif measure_name == 'betweenness':
            node_sizes = [component_df.loc[component_df['reference_form'] == subgraph.nodes[node]['reference_form']].iloc[0]['betweenness_centrality'] * 2000 + 100 for node in subgraph.nodes()]
        elif measure_name == 'eigenvector':
            node_sizes = [component_df.loc[component_df['reference_form'] == subgraph.nodes[node]['reference_form']].iloc[0]['eigenvector_centrality'] * 10000 + 100 for node in subgraph.nodes()]
        else:  # pagerank
            node_sizes = [component_df.loc[component_df['reference_form'] == subgraph.nodes[node]['reference_form']].iloc[0]['pagerank'] * 20000 + 100 for node in subgraph.nodes()]
        
        # Get node colors based on entity type
        node_colors = [entity_colors.get(subgraph.nodes[node]['entity_type'], 'gray') for node in subgraph.nodes()]
        
        # Draw the network
        nx.draw_networkx_edges(subgraph, pos, alpha=0.3, width=0.5)
        
        nx.draw_networkx_nodes(
            subgraph, pos,
            node_size=node_sizes,
            node_color=node_colors,
            alpha=0.7
        )
        
        # Add labels for top 20 nodes only to avoid clutter
        top_limit = min(20, len(node_sizes))
        top_indices = sorted(range(len(node_sizes)), key=lambda i: node_sizes[i], reverse=True)[:top_limit]
        top_nodes = [list(subgraph.nodes())[i] for i in top_indices]
        labels = {node: subgraph.nodes[node]['english_transcription'] for node in top_nodes}
        
        nx.draw_networkx_labels(
            subgraph, pos,
            labels=labels,
            font_size=10,
            font_weight='bold'
        )
        
        plt.title(f"Component {component_id}: Proper Noun Network (Top {len(measure_df)} by {measure_name.capitalize()} Centrality)")
        plt.axis('off')
        
        # Save the figure
        filename = os.path.join(component_dir, f"network_by_{measure_name}.png")
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"Saved component {component_id} visualization to {filename}")
    
    # Save the component network data for D3 visualization
    export_component_for_d3(G, component_id, component_df, component_dir)
    
    # Create component HTML
    create_component_html(component_id, component_dir, output_dir)

def create_component_html(component_id, component_dir, output_dir):
    """Create the HTML file for a specific component."""
    # Get the component HTML template
    _, component_html_template = create_d3_html_template(output_dir)
    
    # Replace placeholders with actual component ID
    component_html = component_html_template.replace('{component_id}', str(component_id))
    
    # Write to file
    component_html_path = os.path.join(output_dir, f"component_{component_id}.html")
    with open(component_html_path, 'w', encoding='utf-8') as f:
        f.write(component_html)
        
    print(f"Created component HTML for component {component_id}")

def export_component_for_d3(G, component_id, component_df, output_dir):
    """Export a single component's network data for D3.js visualization."""
    # Create a dictionary to store centrality values
    centrality_data = {}
    for _, row in component_df.iterrows():
        node_key = (row['reference_form'], row['entity_type'])
        centrality_data[node_key] = {
            'degree': row['degree_centrality'],
            'betweenness': row['betweenness_centrality'],
            'eigenvector': row['eigenvector_centrality'],
            'pagerank': row['pagerank'],
            'clustering': row['clustering_coefficient']
        }
    
    # Prepare nodes with attributes
    nodes = []
    for node, attrs in G.nodes(data=True):
        if node in centrality_data:
            nodes.append({
                'id': f"{node[0]}_{node[1]}",  # Create a unique string ID
                'reference_form': node[0],
                'entity_type': node[1],
                'english_name': attrs['english_transcription'],
                'degree_centrality': centrality_data[node]['degree'],
                'betweenness_centrality': centrality_data[node]['betweenness'],
                'eigenvector_centrality': centrality_data[node]['eigenvector'],
                'pagerank': centrality_data[node]['pagerank'],
                'clustering_coefficient': centrality_data[node]['clustering']
            })
    
    # Prepare edges with weights
    links = []
    for u, v, attrs in G.edges(data=True):
        source_id = f"{u[0]}_{u[1]}"
        target_id = f"{v[0]}_{v[1]}"
        # Check if both nodes are in the component
        if any(n['id'] == source_id for n in nodes) and any(n['id'] == target_id for n in nodes):
            links.append({
                'source': source_id,
                'target': target_id,
                'weight': attrs.get('weight', 1)
            })
    
    # Combine into a single object
    data = {
        'nodes': nodes,
        'links': links,
        'component_id': component_id
    }
    
    # Save to file
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, "network_data.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Exported component {component_id} network data for D3 to {filename}")

def visualize_network(full_graph, all_centrality_df, component_graphs, output_dir, top_n=100):
    """Visualize each network component and generate an overview visualization."""
    # Make sure the output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Create the HTML templates
    create_d3_html_template(output_dir)
    
    # Create a component map visualization
    plt.figure(figsize=(16, 16))
    
    # Color map for components (cycle through colors)
    cmap = plt.get_cmap('tab20', len(component_graphs))
    
    # Use spring layout for the full graph
    pos = nx.spring_layout(full_graph, seed=42, k=0.3, iterations=100)
    
    # Draw each component with a different color
    for comp_id, subgraph in component_graphs:
        nx.draw_networkx_nodes(
            subgraph, pos,
            node_size=20,
            node_color=[cmap(comp_id % 20)] * subgraph.number_of_nodes(),
            alpha=0.7,
            label=f"Component {comp_id} ({subgraph.number_of_nodes()} nodes)"
        )
        nx.draw_networkx_edges(
            subgraph, pos,
            alpha=0.2,
            width=0.3
        )
    
    plt.title(f"Eusebius Proper Noun Network - {len(component_graphs)} Components")
    plt.axis('off')
    plt.legend(loc='lower center', ncol=5, bbox_to_anchor=(0.5, -0.05))
    
    # Save the figure
    filename = os.path.join(output_dir, "component_map.png")
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"Saved component map visualization to {filename}")
    
    # Visualize each component separately
    for comp_id, subgraph in component_graphs:
        if subgraph.number_of_nodes() > 2:  # Skip very small components
            comp_df = all_centrality_df[all_centrality_df['component_id'] == comp_id]
            visualize_component(subgraph, comp_id, comp_df, output_dir, top_n)
    
    # Export the full network data for D3
    export_for_d3(full_graph, component_graphs, all_centrality_df, os.path.join(output_dir, "network_data.json"))

def export_for_d3(G, component_graphs, all_centrality_df, filename):
    """Export the complete network data with component info for D3.js visualization."""
    # Create a dictionary to store centrality values
    centrality_data = {}
    for _, row in all_centrality_df.iterrows():
        node_key = (row['reference_form'], row['entity_type'])
        if node_key not in centrality_data:
            centrality_data[node_key] = {
                'component_id': row['component_id'],
                'degree': row['degree_centrality'],
                'betweenness': row['betweenness_centrality'],
                'eigenvector': row['eigenvector_centrality'],
                'pagerank': row['pagerank'],
                'clustering': row['clustering_coefficient']
            }
    
    # Prepare nodes with attributes
    nodes = []
    for node, attrs in G.nodes(data=True):
        if node in centrality_data:
            nodes.append({
                'id': f"{node[0]}_{node[1]}",  # Create a unique string ID
                'reference_form': node[0],
                'entity_type': node[1],
                'english_name': attrs['english_transcription'],
                'component': centrality_data[node]['component_id'],
                'degree_centrality': centrality_data[node]['degree'],
                'betweenness_centrality': centrality_data[node]['betweenness'],
                'eigenvector_centrality': centrality_data[node]['eigenvector'],
                'pagerank': centrality_data[node]['pagerank'],
                'clustering_coefficient': centrality_data[node]['clustering']
            })
    
    # Prepare edges with weights
    links = []
    for u, v, attrs in G.edges(data=True):
        links.append({
            'source': f"{u[0]}_{u[1]}",
            'target': f"{v[0]}_{v[1]}",
            'weight': attrs.get('weight', 1)
        })
    
    # Prepare component data
    components = []
    for comp_id, subgraph in component_graphs:
        components.append({
            'id': comp_id,
            'size': subgraph.number_of_nodes(),
            'edges': subgraph.number_of_edges()
        })
    
    # Combine into a single object
    data = {
        'nodes': nodes,
        'links': links,
        'components': components
    }
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # Save to file
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Exported full network data for D3 visualization to {filename}")

def modify_website_for_network_viz(output_dir):
    """Modify the main website's navigation to include network visualization."""
    # Define the path to the site's home page
    index_path = os.path.join(output_dir, '..', 'index.html')
    
    # Check if file exists
    if not os.path.exists(index_path):
        print(f"Warning: Cannot find main website index at {index_path}")
        return
    
    try:
        # Read the current content
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find the navigation section
        nav_start = content.find('<nav>')
        nav_end = content.find('</nav>', nav_start)
        
        if nav_start >= 0 and nav_end > nav_start:
            # Extract the navigation
            nav_content = content[nav_start + 5:nav_end].strip()
            
            # Check if network analysis link already exists
            if 'Network Analysis' not in nav_content:
                # Add the new link
                new_nav = nav_content + '\n            <a href="network_viz/index.html">Network Analysis</a>'
                
                # Replace the old navigation with the new one
                content = content[:nav_start + 5] + new_nav + content[nav_end:]
                
                # Write the updated content
                with open(index_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                print(f"Updated main website navigation to include Network Analysis link")
            else:
                print("Network Analysis link already exists in the navigation")
        else:
            print("Could not find navigation section in the main website index")
    
    except Exception as e:
        print(f"Error updating main website navigation: {e}")

if __name__ == '__main__':
    args = parse_arguments()
    
    # Connect to the database
    conn = sqlite3.connect(args.database)
    
    try:
        # Create the centrality table if it doesn't exist
        create_centrality_table(conn)
        
        # Clear existing centrality data
        clear_centrality_table(conn)
        
        # Get nodes and co-occurrences
        print("Fetching proper noun data...")
        nodes_df = get_noun_nodes(conn)
        cooccurrences_df = get_cooccurrences(conn)
        
        if len(nodes_df) == 0:
            print("No proper nouns found in the database.")
            sys.exit(0)
        
        print(f"Found {len(nodes_df)} distinct proper nouns.")
        
        # Build the graph
        print("Building the network graph...")
        full_graph = build_graph(nodes_df, cooccurrences_df, args.min_cooccurrence)
        
        # Break the graph into connected components
        print("Breaking the graph into connected components...")
        component_graphs, node_to_component = get_connected_components(full_graph)
        
        # Calculate centrality measures for each component
        all_centrality_data = []
        for comp_id, component_graph in component_graphs:
            component_centrality = calculate_centrality_measures(component_graph, comp_id)
            all_centrality_data.append(component_centrality)
        
        # Combine all centrality data
        if all_centrality_data:
            all_centrality_df = pd.concat(all_centrality_data, ignore_index=True)
            
            # Save to database
            print("Saving centrality measures to database...")
            save_centrality_measures(conn, all_centrality_df)
            
            # Visualize the network
            print("Generating network visualizations...")
            visualize_network(full_graph, all_centrality_df, component_graphs, args.output_dir, args.top_nodes)
            
            # Modify main website to include network visualization link
            print("Updating main website navigation...")
            modify_website_for_network_viz(args.output_dir)
        else:
            print("No centrality data to save or visualize.")
        
        print("Network analysis complete.")
    
    except Exception as e:
        # Let exception bubble up
        raise e
    
    finally:
        conn.close()

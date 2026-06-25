#!/usr/bin/env python3
"""
Generates a publication-quality vector graphic (PDF) representing
the ServiceScope-v1 dependency graph with actual inferred confidence weights.
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend to avoid GUI window requirements

import networkx as nx
import matplotlib.pyplot as plt

def main():
    # 1. Setup the graph
    G = nx.DiGraph()
    services = [
        'Pipeline Runner', 'Samples App', 'Inference Service',
        'Ollama API', 'Customer Service', 'Payment Service', 'Reporting Service'
    ]
    G.add_nodes_from(services)

    # 2. Add edges with actual inferred confidence weights from servicescope-v1
    edges = [
        ('Pipeline Runner', 'Ollama API', 1.00),
        ('Inference Service', 'Ollama API', 1.00),
        ('Samples App', 'Customer Service', 1.00),
        ('Samples App', 'Payment Service', 0.95),
        ('Samples App', 'Reporting Service', 1.00)
    ]
    G.add_weighted_edges_from([(u, v, w) for u, v, w in edges])

    # 3. Plotting for Academic Publication (LNCS/Springer styling)
    # Customize layout using spring_layout
    pos = nx.spring_layout(G, seed=42, k=1.0)
    plt.figure(figsize=(10, 8))

    # Draw nodes and labels
    nx.draw_networkx_nodes(G, pos, node_color='#DCECF9', node_size=3200, edgecolors='#2C3E50', linewidths=1.5)
    nx.draw_networkx_labels(G, pos, font_size=9, font_weight='bold', font_color='#2C3E50')

    # Draw edges and arrows
    nx.draw_networkx_edges(G, pos, edge_color='#7F8C8D', width=1.5, arrowsize=20, arrowstyle='-|>', connectionstyle='arc3,rad=0.15')

    # Draw confidence weights on edges
    labels = nx.get_edge_attributes(G, 'weight')
    # Format labels to display float values cleanly (e.g. 1.00, 0.95)
    formatted_labels = {edge: f"{weight:.2f}" for edge, weight in labels.items()}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=formatted_labels, font_size=10, font_weight='bold', font_color='#E74C3C', bbox=dict(facecolor='white', edgecolor='none', alpha=0.8))

    plt.title("Fig X. ServiceScope-v1 Dependency Graph with Inferred Confidence Scores", fontsize=12, pad=20, weight='bold')
    plt.axis('off')
    plt.tight_layout()

    # 4. Export as Vector Graphic (Crucial for Springer/LNCS)
    output_filename = "servicescope_v1_graph.pdf"
    plt.savefig(output_filename, format="pdf", bbox_inches="tight")
    print(f"✅ Saved publication-quality vector graphic as: {output_filename}")

if __name__ == "__main__":
    main()

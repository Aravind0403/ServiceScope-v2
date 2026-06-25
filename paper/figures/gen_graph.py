import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ServiceScope-v1 actual dependency graph from blast radius evaluation
# GT edges (5 verified internal dependencies)
G = nx.DiGraph()

services = ['api-gateway', 'customer', 'payment', 'reporting', 'ollama']
G.add_nodes_from(services)

edges = [
    ('api-gateway', 'customer',  0.95),
    ('api-gateway', 'payment',   0.95),
    ('api-gateway', 'reporting', 1.00),
    ('api-gateway', 'ollama',    1.00),
    ('reporting',   'ollama',    0.95),
]
for u, v, w in edges:
    G.add_edge(u, v, weight=w)

pos = {
    'api-gateway': (0.5, 1.0),
    'customer':    (0.0, 0.4),
    'payment':     (0.35, 0.4),
    'reporting':   (0.70, 0.4),
    'ollama':      (1.00, 0.4),
}

fig, ax = plt.subplots(figsize=(8, 5))

nx.draw_networkx_nodes(G, pos, node_color='#DCECF9', node_size=3000,
                       edgecolors='#2C3E50', linewidths=1.5, ax=ax)
nx.draw_networkx_labels(G, pos, font_size=9, font_weight='bold',
                        font_color='#2C3E50', ax=ax)
nx.draw_networkx_edges(G, pos, edge_color='#7F8C8D', width=1.5,
                       arrowsize=18, arrowstyle='-|>',
                       connectionstyle='arc3,rad=0.08', ax=ax)

edge_labels = {(u, v): f"{d['weight']:.2f}" for u, v, d in G.edges(data=True)}
nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels,
                              font_size=8, font_color='#E74C3C',
                              bbox=dict(facecolor='white', edgecolor='none', alpha=0.8),
                              ax=ax)

ax.set_title("Fig. 2. ServiceScope inferred dependency graph with path confidence scores.\n"
             "Edges represent LLM-inferred inter-service calls; weights denote inference confidence.",
             fontsize=10, pad=12)
ax.axis('off')
plt.tight_layout()
plt.savefig("/sessions/fervent-quirky-pasteur/mnt/ServiceScope-v2/paper/figures/servicescope_v1_graph.pdf",
            format="pdf", bbox_inches="tight")
plt.savefig("/sessions/fervent-quirky-pasteur/mnt/ServiceScope-v2/paper/figures/servicescope_v1_graph.png",
            format="png", dpi=150, bbox_inches="tight")
print("Saved PDF and PNG")

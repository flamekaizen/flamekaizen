import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

def save_art():
    # Create an advanced customized 3D data plot / abstract art for the profile
    # representing a neural network loss landscape / mathematical attractor
    fig = plt.figure(figsize=(10, 5), facecolor='none')
    ax = fig.add_subplot(111, projection='3d')
    
    # Make background transparent
    ax.set_facecolor('none')
    ax.grid(False)
    ax.xaxis.pane.fill = False
    ax.yaxis.pane.fill = False
    ax.zaxis.pane.fill = False
    ax.xaxis.pane.set_edgecolor('none')
    ax.yaxis.pane.set_edgecolor('none')
    ax.zaxis.pane.set_edgecolor('none')
    
    # Hide axes ticks
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.axis('off')

    # Mathematics for a complex surface
    X = np.arange(-5, 5, 0.1)
    Y = np.arange(-5, 5, 0.1)
    X, Y = np.meshgrid(X, Y)
    
    # Complex equation representing advanced analytics
    R = np.sqrt(X**2 + Y**2)
    Z = np.sin(R) * np.exp(-R/3) + np.cos(X) * np.sin(Y) * 0.5
    
    # Plot a beautiful wireframe and surface
    surf = ax.plot_surface(X, Y, Z, cmap='magma', edgecolor='none', alpha=0.9, antialiased=True)
    wire = ax.plot_wireframe(X, Y, Z, color='#ffbb00', linewidth=0.3, alpha=0.3)
    
    ax.view_init(elev=35., azim=120)

    # Save as transparent SVG
    plt.savefig('custom_art.svg', format='svg', transparent=True, bbox_inches='tight', pad_inches=0)
    print("Successfully generated custom_art.svg")

if __name__ == "__main__":
    save_art()

import matplotlib
matplotlib.use('Agg')
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.animation import FuncAnimation

def save_animated_art():
    # Build a vibrant dark-mode compliant canvas
    fig = plt.figure(figsize=(8, 6), facecolor='#0D1117') 
    ax = fig.add_subplot(111, projection='3d')
    ax.set_facecolor('#0D1117')
    
    # Completely remove all axes/grids for floating aesthetic
    ax.grid(False)
    for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
        pane.fill = False
        pane.set_edgecolor('none')
    
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.axis('off')

    # Generating a dynamic 3D neural-loss surface mathematically (optimized mesh)
    X = np.arange(-5, 5, 0.3)
    Y = np.arange(-5, 5, 0.3)
    X, Y = np.meshgrid(X, Y)
    
    R = np.sqrt(X**2 + Y**2)
    Z = np.sin(R) * np.exp(-R/4) + np.cos(X) * np.sin(Y) * 0.4
    
    surf = ax.plot_surface(X, Y, Z, cmap='magma', edgecolor='none', alpha=0.95, antialiased=True)
    wire = ax.plot_wireframe(X, Y, Z, color='#ffbb00', linewidth=0.3, alpha=0.5)
    
    # Setup Procedural Rotation Animation
    def update(frame):
        ax.view_init(elev=40., azim=frame)
        return fig,

    # Render a simpler 36-frame loop for speed and stability
    ani = FuncAnimation(fig, update, frames=np.arange(0, 360, 10), interval=100)
    
    # Export directly to high-quality recursive animated GIF
    ani.save('custom_art.gif', writer='pillow', fps=15)
    print("Successfully generated animated custom_art.gif")

if __name__ == "__main__":
    save_animated_art()

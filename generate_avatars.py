import os

def create_avatars():
    os.makedirs("Images/avatars", exist_ok=True)
    
    # 20 distinct beautiful colors/gradients and shapes
    gradients = [
        # (gradient_start, gradient_end, shape_color)
        ("#ff007f", "#7f00ff", "#ffffff"),
        ("#00f2fe", "#4facfe", "#ffffff"),
        ("#ff0844", "#ffb199", "#ffffff"),
        ("#f12711", "#f5af19", "#ffffff"),
        ("#11998e", "#38ef7d", "#ffffff"),
        ("#3a7bd5", "#3a6073", "#ffffff"),
        ("#7f00ff", "#e100ff", "#ffffff"),
        ("#f857a6", "#ff5858", "#ffffff"),
        ("#00c6ff", "#0072ff", "#ffffff"),
        ("#fbc2eb", "#a6c1ee", "#ffffff"),
        ("#84fab0", "#8fd3f4", "#ffffff"),
        ("#a1c4fd", "#c2e9fb", "#ffffff"),
        ("#ff9a9e", "#fecfef", "#ffffff"),
        ("#f6d365", "#fda085", "#ffffff"),
        ("#a8ff78", "#78ffd6", "#ffffff"),
        ("#1a2a6c", "#b21f1f", "#fdbb2d"),
        ("#ee0979", "#ff6a00", "#ffffff"),
        ("#43c6ac", "#191654", "#ffffff"),
        ("#ff00cc", "#333399", "#ffffff"),
        ("#0575e6", "#00f260", "#ffffff")
    ]
    
    for i, (g_start, g_end, s_color) in enumerate(gradients, 1):
        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
  <defs>
    <linearGradient id="grad{i}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{g_start};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{g_end};stop-opacity:1" />
    </linearGradient>
  </defs>
  <circle cx="50" cy="50" r="48" fill="url(#grad{i})" />
  <!-- Minimalist Face -->
  <circle cx="35" cy="40" r="6" fill="{s_color}" opacity="0.9" />
  <circle cx="65" cy="40" r="6" fill="{s_color}" opacity="0.9" />
  <path d="M 35 60 A 15 15 0 0 0 65 60" stroke="{s_color}" stroke-width="4" stroke-linecap="round" fill="none" opacity="0.9" />
</svg>"""
        
        with open(f"Images/avatars/avatar_{i}.svg", "w", encoding="utf-8") as f:
            f.write(svg_content)
            
    print("SUCCESS: 20 default SVG avatars generated successfully in Images/avatars/!")

if __name__ == "__main__":
    create_avatars()

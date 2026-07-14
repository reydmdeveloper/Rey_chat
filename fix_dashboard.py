import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all simple dashboard redirects
content = content.replace('url_for("dashboard")', 'url_for("chat")')

# We need to replace the dashboard route.
# The route starts at @app.route("/dashboard") and ends at return render_template(... all_users_today=all_users_today, )

pattern = re.compile(r'@app\.route\("/dashboard"\)\n@login_required\ndef dashboard\(\):.*?all_users_today=all_users_today,\n    \)', re.DOTALL)

def replacer(match):
    return '@app.route("/dashboard")\n@login_required\ndef dashboard():\n    return redirect(url_for("chat"))'

new_content = pattern.sub(replacer, content)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Dashboard routes updated successfully!")

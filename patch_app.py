import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update payload in handle_message
payload_target = '''    payload = {
        "id": msg_id,
        "sender_name": session['full_name'],
        "sender_id": session['user_id'],'''
        
payload_replace = '''    payload = {
        "id": msg_id,
        "conversation_id": data['conversation_id'],
        "sender_name": session['full_name'],
        "sender_id": session['user_id'],'''

content = content.replace(payload_target, payload_replace)

# 2. Inject /api/chat/recent endpoint before @app.route('/api/chat/messages/<conversation_id>')
recent_endpoint = '''@app.route("/api/chat/recent")
@login_required
def get_recent_messages():
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    # Get the latest message for every conversation
    cur.execute("""
        SELECT m.conversation_id, m.message_text, m.message_type 
        FROM messages m
        INNER JOIN (
            SELECT conversation_id, MAX(id) as max_id 
            FROM messages 
            GROUP BY conversation_id
        ) latest ON m.conversation_id = latest.conversation_id AND m.id = latest.max_id
    """)
    recents = cur.fetchall()
    cur.close()
    conn.close()
    
    recent_dict = {r['conversation_id']: (r['message_type'] if r['message_type'] != 'text' else r['message_text']) for r in recents}
    return jsonify(recent_dict)

'''

content = content.replace('@app.route("/api/chat/messages/<conversation_id>")', recent_endpoint + '@app.route("/api/chat/messages/<conversation_id>")')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated app.py successfully')

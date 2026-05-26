import re
import os

# Update app.py
with open('app.py', 'r', encoding='utf-8') as f:
    app_content = f.read()

# 1. Update the upload function
upload_target = '''    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    save_path = os.path.join(onedrive_base_path, unique_name)
    
    file.save(save_path)
    return jsonify({
        "success": True, 
        "file_name": filename,
        "local_url": unique_name
    })'''

upload_replace = '''    conversation_id = request.form.get('conversation_id', 'unknown_chat')
    username = secure_filename(session.get('full_name', 'User'))
    save_dir = os.path.join(onedrive_base_path, username, conversation_id)
    
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        pass
        
    filename = secure_filename(file.filename)
    save_path = os.path.join(save_dir, filename)
    
    # Handle name collisions by appending a number
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(save_path):
        filename = f"{base}_{counter}{ext}"
        save_path = os.path.join(save_dir, filename)
        counter += 1
    
    file.save(save_path)
    
    relative_url = f"{username}/{conversation_id}/{filename}"
    
    return jsonify({
        "success": True, 
        "file_name": filename,
        "local_url": relative_url
    })'''

app_content = app_content.replace(upload_target, upload_replace)

# 2. Update the download function
download_target = '''@app.route("/api/chat/download/<filename>")
@login_required
def download_file(filename):'''

download_replace = '''@app.route("/api/chat/download/<path:filename>")
@login_required
def download_file(filename):'''

app_content = app_content.replace(download_target, download_replace)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(app_content)
print("Updated app.py")


# Update chat.html
with open('templates/chat.html', 'r', encoding='utf-8') as f:
    chat_content = f.read()

chat_target = '''        const fd = new FormData();
        fd.append('file', file);
        
        fetch('/api/chat/upload', {'''

chat_replace = '''        const fd = new FormData();
        fd.append('file', file);
        fd.append('conversation_id', currentRoom);
        
        fetch('/api/chat/upload', {'''

chat_content = chat_content.replace(chat_target, chat_replace)

with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write(chat_content)
print("Updated chat.html")

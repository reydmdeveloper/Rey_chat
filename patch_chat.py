import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix app-container CSS
css_target = '''    .app-container {
        width: 100%;
        max-width: 1400px;
        height: 95vh;
        display: flex;
        overflow: hidden;
        animation: scaleIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    }'''
    
css_replace = '''    .app-container {
        width: 100vw;
        max-width: none;
        height: 100vh;
        border-radius: 0;
        border: none;
        display: flex;
        overflow: hidden;
        animation: scaleIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    }'''
content = content.replace(css_target, css_replace)

# Inject fetch for recent messages
# And add optimistic UI

js_patch = '''
    let recentMessages = {};
    
    async function loadRecents() {
        try {
            const res = await fetch('/api/chat/recent');
            recentMessages = await res.json();
        } catch(e) {
            console.error('Error fetching recents', e);
        }
    }
'''

content = content.replace('const UID = {{ current_user_id }};', 'const UID = {{ current_user_id }};\n' + js_patch)

# Update loadUsers
load_users_pattern = re.compile(r'el\.innerHTML = `(.*?)<div style="font-size: 12px; color: var\(--text-muted\);\">\$\{u\.role === \'admin\' \? \'Admin\' : \'User\'\}</div>(.*?)`;', re.DOTALL)
def users_repl(m):
    return f'''el.innerHTML = `{m.group(1)}<div style="font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center;"><span>${{u.role === 'admin' ? 'Admin' : 'User'}}</span><span style="max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-left: 10px; font-style: italic;">${{recentMessages[generateRoomId(UID, u.id)] || ''}}</span></div>{m.group(2)}`;'''
content = load_users_pattern.sub(users_repl, content)

# Update loadGroups
load_groups_pattern = re.compile(r'el\.innerHTML = `(.*?)<div style="font-size: 12px; color: var\(--text-muted\);\">Group</div>(.*?)`;', re.DOTALL)
def groups_repl(m):
    return f'''el.innerHTML = `{m.group(1)}<div style="font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between; align-items: center;"><span>Group</span><span style="max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-left: 10px; font-style: italic;">${{recentMessages['group_' + g.id] || ''}}</span></div>{m.group(2)}`;'''
content = load_groups_pattern.sub(groups_repl, content)

# Update sendMsg for optimistic UI
send_msg_target = '''    // Actions
    function sendMsg() {
        const inp = document.getElementById('msgIn');
        const txt = inp.value.trim();
        if (!txt || !currentRoom) return;
        
        socket.emit('send_message', {
            conversation_id: currentRoom,
            text: txt,
            type: 'text',
            reply_to_id: replyToMsgId
        });
        inp.value = '';
        inp.style.height = '50px';
        cancelReply();
    }'''
    
send_msg_replace = '''    // Actions
    function sendMsg() {
        const inp = document.getElementById('msgIn');
        const txt = inp.value.trim();
        if (!txt || !currentRoom) return;
        
        // Optimistic UI Render
        const tempId = 'temp_' + Date.now();
        const tempMsg = {
            id: tempId,
            conversation_id: currentRoom,
            sender_id: UID,
            sender_name: "{{ current_user_name }}",
            message_text: txt,
            message_type: 'text',
            created_at: new Date().toLocaleTimeString(),
            is_temp: true
        };
        renderMsg(tempMsg);
        scrollToBottom();
        
        socket.emit('send_message', {
            conversation_id: currentRoom,
            text: txt,
            type: 'text',
            reply_to_id: replyToMsgId
        });
        inp.value = '';
        inp.style.height = '50px';
        cancelReply();
    }'''

content = content.replace(send_msg_target, send_msg_replace)

# Modify new_message socket handler
new_msg_target = '''    // WebSocket Events
    socket.on('new_message', function(msg) {
        document.getElementById('typing-indicator').style.display = 'none';
        
        if (msg.conversation_id === currentRoom) {
            renderMsg(msg);
            scrollToBottom();
        }'''
new_msg_replace = '''    // WebSocket Events
    socket.on('new_message', function(msg) {
        document.getElementById('typing-indicator').style.display = 'none';
        
        if (msg.sender_id === UID) {
            // Remove optimistic temp message
            const temps = document.querySelectorAll('.msg-wrapper[id^="msg-wrapper-temp_"]');
            if(temps.length) temps[0].remove();
        }
        
        if (msg.conversation_id === currentRoom) {
            renderMsg(msg);
            scrollToBottom();
        }'''
content = content.replace(new_msg_target, new_msg_replace)

content = content.replace('loadUsers();\n    loadGroups();', 'loadRecents().then(() => {\n        loadUsers();\n        loadGroups();\n    });')

with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated chat.html successfully')

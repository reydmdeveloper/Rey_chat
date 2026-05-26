import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update renderMsg: add Save button and safeText
render_target = '''            } else {
                contentHtml = `
                <div class="msg-bubble">
                    ${replyHtml}
                    <i class="fa-solid fa-file"></i> Sent a file
                    <div class="msg-file">
                        <i class="fa-solid fa-paperclip msg-file-icon"></i>
                        <div class="msg-file-name" title="${msg.file_name}">${msg.file_name}</div>
                        <a href="${msg.file_url}" target="_blank" class="msg-file-btn">Open</a>
                    </div>
                </div>`;
            }'''

render_replace = '''            } else {
                contentHtml = `
                <div class="msg-bubble">
                    ${replyHtml}
                    ${safeText ? '<div style="margin-bottom: 10px;">' + safeText + '</div>' : ''}
                    <div class="msg-file">
                        <i class="fa-solid fa-paperclip msg-file-icon"></i>
                        <div class="msg-file-name" title="${msg.file_name}">${msg.file_name}</div>
                        <a href="/api/chat/download/${msg.file_url}" target="_blank" class="msg-file-btn">Open</a>
                        <a href="/api/chat/download/${msg.file_url}" download="${msg.file_name}" class="msg-file-btn" style="background: rgba(16, 185, 129, 0.2); color: #34d399; margin-left: 5px;">Save <i class="fa-solid fa-download"></i></a>
                    </div>
                </div>`;
            }'''
content = content.replace(render_target, render_replace)

# Also update image and audio rendering to show safeText
image_target = '''            if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
                contentHtml = `<div class="msg-bubble" style="padding: 5px;">${replyHtml}<img src="${msg.file_url}" alt="${msg.file_name}" style="max-width: 250px; border-radius: 12px; display: block;"></div>`;
            } else if (['mp3', 'wav', 'ogg', 'webm'].includes(ext)) {
                contentHtml = `<div class="msg-bubble" style="padding: 10px; min-width: 200px;">${replyHtml}<audio controls src="${msg.file_url}" style="width: 100%; height: 35px; outline: none;"></audio></div>`;'''

image_replace = '''            if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
                contentHtml = `<div class="msg-bubble" style="padding: 5px;">${replyHtml}${safeText ? '<div style="padding: 5px 10px;">' + safeText + '</div>' : ''}<img src="/api/chat/download/${msg.file_url}" alt="${msg.file_name}" style="max-width: 250px; border-radius: 12px; display: block;"><div style="text-align: right; margin-top: 5px;"><a href="/api/chat/download/${msg.file_url}" download="${msg.file_name}" class="msg-file-btn" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">Save <i class="fa-solid fa-download"></i></a></div></div>`;
            } else if (['mp3', 'wav', 'ogg', 'webm'].includes(ext)) {
                contentHtml = `<div class="msg-bubble" style="padding: 10px; min-width: 200px;">${replyHtml}${safeText ? '<div style="margin-bottom: 5px;">' + safeText + '</div>' : ''}<audio controls src="/api/chat/download/${msg.file_url}" style="width: 100%; height: 35px; outline: none; margin-bottom: 5px;"></audio><div style="text-align: right;"><a href="/api/chat/download/${msg.file_url}" download="${msg.file_name}" class="msg-file-btn" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">Save <i class="fa-solid fa-download"></i></a></div></div>`;'''

content = content.replace(image_target, image_replace)


# 2. Add Staged File variable and Staging UI
staged_file_var = '''    let replyToMsgId = null;
    let stagedFile = null;'''
content = content.replace("    let replyToMsgId = null;", staged_file_var)

staging_ui = '''        <!-- File Staging Banner -->
        <div class="reply-banner" id="stagedFileBanner" style="background: rgba(99, 102, 241, 0.1); border-left-color: var(--primary);">
            <div style="flex:1;">
                <div style="font-size: 12px; color: var(--primary); font-weight: bold;"><i class="fa-solid fa-paperclip"></i> Attached File</div>
                <div style="font-size: 13px;" id="stagedFileName"></div>
            </div>
            <i class="fa-solid fa-times msg-delete" onclick="cancelStagedFile()" style="font-size: 16px;"></i>
        </div>'''
        
content = content.replace('<div class="reply-banner" id="replyBanner">', staging_ui + '\n        <div class="reply-banner" id="replyBanner">')


# 3. Update handleFileUpload
handle_file_target = '''    function handleFileUpload(droppedFile = null) {
        let file;
        if (droppedFile && droppedFile.name) {
            file = droppedFile;
        } else {
            file = document.getElementById('fileInput').files[0];
        }
        if(!file || !currentRoom) return;
        
        const fd = new FormData();
        fd.append('file', file);
        fd.append('conversation_id', currentRoom);
        
        fetch('/api/chat/upload', {
            method: 'POST',
            body: fd
        }).then(res => res.json()).then(data => {
            if(data.success) {
                socket.emit('send_message', {
                    conversation_id: currentRoom,
                    type: 'file',
                    file_name: data.file_name,
                    file_url: data.local_url,
                    reply_to_id: replyToMsgId
                });
                cancelReply();
            } else {
                alert("Upload failed: " + (data.message || "Unknown error"));
            }
        }).catch(err => {
            alert("Upload failed. Check your connection.");
        });
        
        document.getElementById('fileInput').value = '';
    }'''

handle_file_replace = '''    function handleFileUpload(droppedFile = null) {
        let file;
        if (droppedFile && droppedFile.name) {
            file = droppedFile;
        } else {
            file = document.getElementById('fileInput').files[0];
        }
        if(!file || !currentRoom) return;
        
        stagedFile = file;
        document.getElementById('stagedFileName').textContent = file.name;
        document.getElementById('stagedFileBanner').style.display = 'flex';
        document.getElementById('msgIn').focus();
        document.getElementById('fileInput').value = '';
    }
    
    function cancelStagedFile() {
        stagedFile = null;
        document.getElementById('stagedFileBanner').style.display = 'none';
    }'''
content = content.replace(handle_file_target, handle_file_replace)


# 4. Update sendMsg
send_msg_target = '''    function sendMsg() {
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

send_msg_replace = '''    async function sendMsg() {
        const inp = document.getElementById('msgIn');
        const txt = inp.value.trim();
        if (!txt && !stagedFile) return;
        if (!currentRoom) return;
        
        if (stagedFile) {
            // Create a temp message indicating uploading
            const tempId = 'temp_' + Date.now();
            const tempMsg = {
                id: tempId,
                conversation_id: currentRoom,
                sender_id: UID,
                sender_name: "{{ current_user_name }}",
                message_text: txt ? txt : 'Uploading file...',
                message_type: 'text',
                created_at: new Date().toLocaleTimeString(),
                is_temp: true
            };
            renderMsg(tempMsg);
            scrollToBottom();
            
            const fd = new FormData();
            fd.append('file', stagedFile);
            fd.append('conversation_id', currentRoom);
            
            try {
                const res = await fetch('/api/chat/upload', {
                    method: 'POST',
                    body: fd
                });
                const data = await res.json();
                
                // Remove optimistic temp message
                const temps = document.querySelectorAll('#msg-wrapper-' + tempId);
                if(temps.length) temps[0].remove();
                
                if(data.success) {
                    socket.emit('send_message', {
                        conversation_id: currentRoom,
                        text: txt,
                        type: 'file',
                        file_name: data.file_name,
                        file_url: data.local_url,
                        reply_to_id: replyToMsgId
                    });
                } else {
                    alert("Upload failed: " + (data.message || "Unknown error"));
                }
            } catch(err) {
                // Remove temp message
                const temps = document.querySelectorAll('#msg-wrapper-' + tempId);
                if(temps.length) temps[0].remove();
                alert("Upload failed. Check your connection.");
            }
            cancelStagedFile();
        } else {
            // Optimistic UI Render for text
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
        }
        
        inp.value = '';
        inp.style.height = '50px';
        cancelReply();
    }'''
content = content.replace(send_msg_target, send_msg_replace)

with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write(content)
print('Successfully patched file uploads!')

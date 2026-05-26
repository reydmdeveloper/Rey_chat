with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

ids = ['chatName', 'chatAvatar', 'notifBadge', 'stagedFileName', 'stagedFileBanner', 
       'pinnedText', 'pinnedBanner', 'replyToName', 'replyToSnippet', 'forwardSnippet',
       'notifDropdown', 'notifList']
for term in ids:
    count = content.count('id="' + term + '"')
    print(f'{term}: found {count} times as id attribute')

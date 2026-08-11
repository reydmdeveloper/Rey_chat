const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 8090;
const UPLOAD_DIR = path.join(__dirname, 'node_uploads');

if (!fs.existsSync(UPLOAD_DIR)) {
    fs.mkdirSync(UPLOAD_DIR, { recursive: true });
}

const destStorage = multer.diskStorage({
    destination: (req, file, cb) => cb(null, UPLOAD_DIR),
    filename: (req, file, cb) => {
        const unique = Date.now() + '-' + Math.random().toString(36).slice(2, 8);
        const ext = path.extname(file.originalname);
        cb(null, unique + ext);
    }
});

const upload = multer({ storage: destStorage, limits: { fileSize: 500 * 1024 * 1024 } });

app.use(express.json());

app.use((req, res, next) => {
    res.header('Access-Control-Allow-Origin', '*');
    res.header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Content-Type');
    if (req.method === 'OPTIONS') return res.status(204).end();
    next();
});

const getFilePath = (fileRef) => {
    let ref = fileRef;
    if (ref.startsWith('node:')) ref = ref.slice(5);
    const filePath = path.join(UPLOAD_DIR, ref);
    const realPath = path.resolve(filePath);
    const realUpload = path.resolve(UPLOAD_DIR);
    if (!realPath.startsWith(realUpload)) return null;
    return realPath;
};

app.use((req, res) => {
    const method = req.method;
    const uri = req.path;

    if ((uri === '/' || uri === '/health') && method === 'GET') {
        return res.json({
            success: true,
            message: 'REY Chat Node.js Storage Server running',
            upload_dir: UPLOAD_DIR,
            time: new Date().toISOString()
        });
    }

    if (uri === '/upload' && method === 'POST') {
        return upload.single('file')(req, res, () => {
            if (!req.file) {
                return res.status(400).json({ success: false, message: 'No file uploaded' });
            }
            const userId = req.body.user_id || '0';
            const convId = req.body.conversation_id || 'unknown';
            const destDir = path.join(UPLOAD_DIR, userId, convId);
            fs.mkdirSync(destDir, { recursive: true });

            let safeName = req.file.originalname.replace(/[^a-zA-Z0-9._-]/g, '_');
            const base = path.parse(safeName).name;
            const ext = path.parse(safeName).ext;
            let counter = 1;
            let finalPath = path.join(destDir, safeName);
            while (fs.existsSync(finalPath)) {
                safeName = `${base}_${counter}${ext}`;
                finalPath = path.join(destDir, safeName);
                counter++;
            }

            fs.renameSync(req.file.path, finalPath);

            const ref = `node:${userId}/${convId}/${safeName}`;
            res.json({
                success: true,
                file_name: safeName,
                local_url: ref,
                size: fs.statSync(finalPath).size
            });
        });
    }

    const downloadMatch = uri.match(/^\/download\/(.+)/);
    const openMatch = uri.match(/^\/open\/(.+)/);
    const deleteMatch = uri.match(/^\/delete\/(.+)/);

    if (downloadMatch && method === 'GET') {
        const filePath = getFilePath(downloadMatch[1]);
        if (!filePath || !fs.existsSync(filePath)) {
            return res.status(404).json({ success: false, message: 'File not found' });
        }
        return res.download(filePath, path.basename(filePath));
    }

    if (openMatch && method === 'GET') {
        const filePath = getFilePath(openMatch[1]);
        if (!filePath || !fs.existsSync(filePath)) {
            return res.status(404).json({ success: false, message: 'File not found' });
        }
        return res.sendFile(filePath);
    }

    if (deleteMatch && method === 'DELETE') {
        const filePath = getFilePath(deleteMatch[1]);
        if (!filePath || !fs.existsSync(filePath)) {
            return res.status(404).json({ success: false, message: 'File not found' });
        }
        fs.unlinkSync(filePath);
        return res.json({ success: true, message: 'File deleted' });
    }

    res.status(404).json({ success: false, message: 'Endpoint not found' });
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`REY Chat Node.js Storage Server running on http://0.0.0.0:${PORT}`);
    console.log(`Upload directory: ${UPLOAD_DIR}`);
});

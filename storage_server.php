<?php
/**
 * REY Chat Extra Storage Server (PHP)
 * 
 * Acts as an alternative file storage backend.
 * Run: php -S 0.0.0.0:8089 storage_server.php
 * 
 * Storage mode: extra (local/OneDrive/PHP)
 * If configured, the app can send/receive files to/from this server.
 */

$UPLOAD_DIR = __DIR__ . '/php_uploads';
if (!is_dir($UPLOAD_DIR)) {
    mkdir($UPLOAD_DIR, 0777, true);
}

$METHOD = $_SERVER['REQUEST_METHOD'];
$URI = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($METHOD === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// Health check
if ($URI === '/' || $URI === '/health') {
    echo json_encode([
        'success' => true,
        'message' => 'REY Chat PHP Storage Server running',
        'upload_dir' => $UPLOAD_DIR,
        'time' => date('Y-m-d H:i:s')
    ]);
    exit;
}

// Upload file
if ($URI === '/upload' && $METHOD === 'POST') {
    if (!isset($_FILES['file'])) {
        http_response_code(400);
        echo json_encode(['success' => false, 'message' => 'No file uploaded']);
        exit;
    }

    $file = $_FILES['file'];
    $conversation_id = $_POST['conversation_id'] ?? 'unknown';
    $userId = $_POST['user_id'] ?? '0';

    if ($file['error'] !== UPLOAD_ERR_OK) {
        http_response_code(400);
        echo json_encode(['success' => false, 'message' => 'Upload error: ' . $file['error']]);
        exit;
    }

    $safeName = preg_replace('/[^a-zA-Z0-9._-]/', '_', $file['name']);
    $subDir = $UPLOAD_DIR . '/' . $userId . '/' . $conversation_id;
    if (!is_dir($subDir)) {
        mkdir($subDir, 0777, true);
    }

    $savePath = $subDir . '/' . $safeName;
    $counter = 1;
    $base = pathinfo($safeName, PATHINFO_FILENAME);
    $ext = pathinfo($safeName, PATHINFO_EXTENSION);
    while (file_exists($savePath)) {
        $safeName = $base . '_' . $counter . '.' . $ext;
        $savePath = $subDir . '/' . $safeName;
        $counter++;
    }

    if (move_uploaded_file($file['tmp_name'], $savePath)) {
        $ref = 'php:' . $userId . '/' . $conversation_id . '/' . $safeName;
        echo json_encode([
            'success' => true,
            'file_name' => $safeName,
            'local_url' => $ref,
            'size' => filesize($savePath)
        ]);
    } else {
        http_response_code(500);
        echo json_encode(['success' => false, 'message' => 'Failed to save file']);
    }
    exit;
}

// Download / Open file
if (preg_match('#^/(download|open)/(.+)$#', $URI, $m)) {
    $action = $m[1];
    $fileRef = $m[2];

    // ref format: php:userId/conversationId/filename
    if (strpos($fileRef, 'php:') === 0) {
        $fileRef = substr($fileRef, 4);
    }

    $filePath = $UPLOAD_DIR . '/' . $fileRef;

    // Security check – prevent path traversal
    $realPath = realpath($filePath);
    $realUpload = realpath($UPLOAD_DIR);
    if ($realPath === false || strpos($realPath, $realUpload) !== 0) {
        http_response_code(404);
        echo json_encode(['success' => false, 'message' => 'File not found']);
        exit;
    }

    if (!file_exists($realPath)) {
        http_response_code(404);
        echo json_encode(['success' => false, 'message' => 'File not found on disk']);
        exit;
    }

    $fileName = basename($realPath);
    $mime = mime_content_type($realPath) ?: 'application/octet-stream';

    if ($action === 'open') {
        header('Content-Type: ' . $mime);
        header('Content-Disposition: inline; filename="' . $fileName . '"');
        readfile($realPath);
    } else {
        header('Content-Type: ' . $mime);
        header('Content-Disposition: attachment; filename="' . $fileName . '"');
        header('Content-Length: ' . filesize($realPath));
        readfile($realPath);
    }
    exit;
}

// Delete file
if (preg_match('#^/delete/(.+)$#', $URI, $m) && $METHOD === 'DELETE') {
    $fileRef = $m[1];
    if (strpos($fileRef, 'php:') === 0) {
        $fileRef = substr($fileRef, 4);
    }
    $filePath = $UPLOAD_DIR . '/' . $fileRef;
    $realPath = realpath($filePath);
    $realUpload = realpath($UPLOAD_DIR);
    if ($realPath !== false && strpos($realPath, $realUpload) === 0 && file_exists($realPath)) {
        unlink($realPath);
        echo json_encode(['success' => true, 'message' => 'File deleted']);
    } else {
        http_response_code(404);
        echo json_encode(['success' => false, 'message' => 'File not found']);
    }
    exit;
}

// 404 fallback
http_response_code(404);
echo json_encode(['success' => false, 'message' => 'Endpoint not found']);

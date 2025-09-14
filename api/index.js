// api/index.js
const express = require('express');
const multer = require('multer');
const fs = require('fs').promises;
const path = require('path');
const cors = require('cors');
const { Redis } = require('@upstash/redis');

const apiCalls = require('../apiCalls'); // Note the ../ path
const utils = require('../utils');     // Note the ../ path

// --- Application Setup ---
const app = express();
app.use(cors()); // Enable CORS for all origins

// **VERCEL FIX**: Use the /tmp directory for file uploads, as it's the only writable path.
const upload = multer({ dest: '/tmp' });

// --- Persistent State Management with Vercel Redis ---
const redis = new Redis({
  url: process.env.UPSTASH_REDIS_REST_URL,
  token: process.env.UPSTASH_REDIS_REST_TOKEN,
});
const SESSION_KEY = "bank_converter_session";
const MAX_USAGE = 5;
const MAX_REGISTRATION_ATTEMPTS = 3;

async function loadSession() {
    const session = await redis.get(SESSION_KEY);
    return session || { token: null, usage_count: 0 };
}

async function saveSession(sessionData) {
    await redis.set(SESSION_KEY, JSON.stringify(sessionData));
}

// createNewSession and getValidToken now use the async Redis functions
async function createNewSession() {
    console.log("--- Attempting to create a new session ---");
    for (let attempt = 1; attempt <= MAX_REGISTRATION_ATTEMPTS; attempt++) {
        console.log(`Registration attempt ${attempt}/${MAX_REGISTRATION_ATTEMPTS}`);
        const creds = utils.generateRandomCredentials();
        console.log(`Generated new credentials for: ${creds.email}`);
        try {
            const registerResponse = await apiCalls.registerUser(creds.email, creds.password, creds.firstName, creds.lastName);
            if (registerResponse.status === 200 || registerResponse.status === 201) {
                console.log("Registration successful.");
                const emailId = await apiCalls.checkInbox(creds.email);
                const htmlContent = await apiCalls.readEmail(emailId);
                if (!htmlContent) throw new Error("Failed to read email content.");
                const verificationLink = utils.extractVerificationLinkFromHtml(htmlContent);
                if (!verificationLink) throw new Error("Failed to extract verification link.");
                await apiCalls.verifyEmailAccount(verificationLink);
                const token = await apiCalls.login(creds.email, creds.password);
                const newSession = { token, usage_count: 0 };
                await saveSession(newSession);
                console.log("--- New session created and saved successfully ---");
                return newSession;
            } else {
                console.error(`Registration failed with status ${registerResponse.status}.`);
            }
        } catch (error) {
            console.error(`Exception during session creation attempt ${attempt}:`, error.message);
        }
    }
    throw new Error("Failed to create a new session after multiple attempts.");
}

async function getValidToken() {
    let session = await loadSession();
    if (!session.token || session.usage_count >= MAX_USAGE) {
        console.log("Token expired or not available. Creating a new session.");
        session = await createNewSession();
    }
    return session.token;
}

// --- API Endpoints ---
app.get('/api', (req, res) => {
    res.status(200).json({ status: "Bank Statement Converter API is fully operational on Vercel" });
});

app.post('/api/convert-statement', upload.single('file'), async (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: "No file part in the request. Key must be 'file'." });
    }
    const tempPath = req.file.path;
    console.log(`File '${req.file.originalname}' saved to '${tempPath}'`);
    try {
        const authToken = await getValidToken();
        console.log("Uploading bank statement...");
        const uploadUuid = await apiCalls.uploadStatement(authToken, tempPath, req.file.originalname);
        console.log(`Upload successful. UUID: ${uploadUuid}`);
        
        const csvData = await apiCalls.pollAndConvertStatement(authToken, uploadUuid);

        const session = await loadSession();
        session.usage_count = (session.usage_count || 0) + 1;
        await saveSession(session);
        console.log(`Token usage updated to: ${session.usage_count}/${MAX_USAGE}`);
        
        res.setHeader('Content-disposition', `attachment; filename=converted_${req.file.originalname}.csv`);
        res.set('Content-Type', 'text/csv');
        res.status(200).send(csvData);

    } catch (error) {
        console.error("An error occurred in the main endpoint:", error.message);
        res.status(500).json({ error: `An internal server error occurred. Check Vercel logs for details.` });
    } finally {
        await fs.unlink(tempPath).catch(err => console.error(`Failed to cleanup temp file: ${err.message}`));
    }
});

// **VERCEL FIX**: Export the Express app instance for Vercel's serverless environment.
// Do NOT call app.listen() here.
module.exports = app;

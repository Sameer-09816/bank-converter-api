// apiCalls.js
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');
const { sleep } = require('./utils');

const BSC_API_BASE = "https://api2.bankstatementconverter.com/api/v1";
const TEMP_MAIL_API_BASE = "https://api.barid.site";
const REQUEST_TIMEOUT = 60000;

// **FIX**: Define a standard set of headers to mimic a browser and satisfy firewalls.
const COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
};

async function pollAndConvertStatement(authToken, uuid) {
    const url = `${BSC_API_BASE}/BankStatement/convert?format=CSV`;
    const payload = `["${uuid}"]`;
    
    // **FIX**: Set specific headers for this request. We expect CSV.
    const headers = {
        ...COMMON_HEADERS,
        "Authorization": authToken,
        "Content-Type": "text/plain;charset=UTF-8",
        "Accept": "text/csv,text/plain,*/*;q=0.8" // Be specific about what we accept
    };
    
    const maxWaitTime = 90000;
    const pollInterval = 3000;
    const startTime = Date.now();

    console.log(`Starting to poll conversion endpoint for UUID ${uuid}...`);

    while (Date.now() - startTime < maxWaitTime) {
        try {
            const response = await axios.post(url, payload, { headers, timeout: REQUEST_TIMEOUT });
            console.log(`Conversion successful for UUID ${uuid}.`);
            return response.data;
        } catch (error) {
            if (error.response && error.response.status === 400) {
                console.log(`File ${uuid} not ready yet (received 400). Retrying...`);
                await sleep(pollInterval);
            } else {
                console.error(`Unexpected error during conversion polling:`, error.message);
                throw error;
            }
        }
    }
    throw new Error(`Conversion timed out for file ${uuid}.`);
}

async function registerUser(email, password, firstName, lastName) {
    const url = `${BSC_API_BASE}/register`;
    const payload = { email, password, firstName, lastName, referredBy: "" };
    // **FIX**: Set specific headers for JSON API calls
    const headers = { ...COMMON_HEADERS, 'Accept': 'application/json' };
    return await axios.post(url, payload, { headers, timeout: REQUEST_TIMEOUT });
}

async function checkInbox(email) {
    const url = `${TEMP_MAIL_API_BASE}/emails/${email}`;
    const headers = { ...COMMON_HEADERS, 'Accept': 'application/json' };
    const maxRetries = 15, retryDelay = 5000;
    for (let i = 0; i < maxRetries; i++) {
        try {
            const response = await axios.get(url, { headers, timeout: REQUEST_TIMEOUT });
            if (response.data?.success && response.data.result?.length > 0) {
                const verificationEmail = response.data.result.find(e => e.subject.toLowerCase().includes('verify email'));
                if (verificationEmail) {
                    console.log(`Verification email found.`);
                    return verificationEmail.id;
                }
            }
        } catch (error) {
            console.warn(`Error checking inbox (attempt ${i + 1}/${maxRetries}):`, error.message);
        }
        console.log(`Email not found yet. Retrying...`);
        await sleep(retryDelay);
    }
    throw new Error("Verification email did not arrive in time.");
}

async function readEmail(emailId) {
    const url = `${TEMP_MAIL_API_BASE}/inbox/${emailId}`;
    const headers = { ...COMMON_HEADERS, 'Accept': 'application/json' };
    const response = await axios.get(url, { headers, timeout: REQUEST_TIMEOUT });
    if (response.data?.success) {
        return response.data.result.html_content;
    }
    throw new Error("Failed to read email content.");
}

async function verifyEmailAccount(verificationLink) {
    // Verification is like a browser click, so it accepts HTML.
    const headers = { ...COMMON_HEADERS, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8' };
    const response = await axios.get(verificationLink, { headers, timeout: REQUEST_TIMEOUT, maxRedirects: 5 });
    console.log(`Verification link accessed. Final URL: ${response.request.res.responseUrl}, Status: ${response.status}`);
    return true;
}

async function login(email, password) {
    const url = `${BSC_API_BASE}/login`;
    const payload = { email, password };
    const headers = { ...COMMON_HEADERS, 'Accept': 'application/json' };
    const response = await axios.post(url, payload, { headers, timeout: REQUEST_TIMEOUT });
    if (response.data?.token) {
        return response.data.token;
    }
    throw new Error("Login failed: token not found.");
}

async function uploadStatement(authToken, filePath, filename) {
    const url = `${BSC_API_BASE}/BankStatement`;
    const form = new FormData();
    form.append('files', fs.createReadStream(filePath), filename);
    
    // **FIX**: Combine form-data headers with our custom headers.
    const formHeaders = form.getHeaders();
    const headers = {
        ...COMMON_HEADERS,
        "Authorization": authToken,
        ...formHeaders,
        "Accept": "application/json" // We expect a JSON response with the UUID
    };
    
    const response = await axios.post(url, form, { headers, timeout: REQUEST_TIMEOUT });

    if (response.data?.[0]?.uuid) {
        return response.data[0].uuid;
    }
    throw new Error(`Upload failed: UUID not found. Response: ${JSON.stringify(response.data)}`);
}

module.exports = {
    pollAndConvertStatement,
    registerUser,
    checkInbox,
    readEmail,
    verifyEmailAccount,
    login,
    uploadStatement,
};

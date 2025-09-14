// utils.js
const cheerio = require('cheerio');

/**
 * Generates random user data with a guaranteed unique email address.
 */
function generateRandomCredentials() {
    const domains = ["vwh.sh", "iusearch.lol", "barid.site", "z44d.pro", "wael.fun", "kuruptd.ink"];
    const randomPart = Math.random().toString(36).substring(2, 10);
    const timestampPart = Date.now();
    const username = `${randomPart}${timestampPart}`;
    const email = `${username}@${domains[Math.floor(Math.random() * domains.length)]}`;

    const password = Math.random().toString(36).substring(2, 14);
    const firstName = Math.random().toString(36).substring(2, 8);
    const lastName = Math.random().toString(36).substring(2, 8);

    return { email, password, firstName, lastName };
}

/**
 * Uses cheerio to safely parse HTML and find the verification link.
 * @param {string} htmlContent - The HTML content of the email.
 * @returns {string|null} The verification URL or null if not found.
 */
function extractVerificationLinkFromHtml(htmlContent) {
    try {
        const $ = cheerio.load(htmlContent);
        const linkElement = $("a").filter((i, el) => {
            return $(el).text().trim().toLowerCase().includes('verify my email');
        });
        const link = linkElement.attr('href');
        return link || null;
    } catch (error) {
        console.error("Error parsing HTML for verification link:", error);
        return null;
    }
}

/**
 * A simple promise-based sleep function.
 * @param {number} ms - The number of milliseconds to wait.
 */
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

module.exports = {
    generateRandomCredentials,
    extractVerificationLinkFromHtml,
    sleep
};

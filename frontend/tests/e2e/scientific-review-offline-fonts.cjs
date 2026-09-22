// Next's own test hook prevents Google Fonts network access. System fallback
// typography is intentional in this offline visual test, not a font canary.
module.exports = new Proxy({}, { get: () => "@font-face { font-family: 'Inter'; src: local('Arial'); font-style: normal; font-weight: 100 900; font-display: swap; }" });

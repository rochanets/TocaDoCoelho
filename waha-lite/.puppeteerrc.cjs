/**
 * Pula o download do Chromium embutido.
 * O waha-lite usa o Chrome/Edge já instalado no sistema (Win10/11 sempre tem Edge).
 * @type {import("puppeteer").Configuration}
 */
module.exports = {
  skipDownload: true,
};

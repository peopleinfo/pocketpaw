const puppeteer = require('puppeteer');
(async () => {
    const browser = await puppeteer.launch();
    const page = await browser.newPage();
    await page.goto('http://localhost:8888/#/anti-browser', {waitUntil: 'networkidle0'});
    
    // Check if select has options
    const options = await page.evaluate(() => {
        const select = document.querySelector('select[x-model="antiBrowser.form.plugin"]');
        return Array.from(select.options).map(o => ({
            value: o.value,
            text: o.text,
            disabled: o.disabled
        }));
    });
    console.log(JSON.stringify(options));
    await browser.close();
})();

const puppeteer = require('puppeteer');
(async () => {
    const browser = await puppeteer.launch();
    const page = await browser.newPage();
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    await page.goto('http://localhost:8888/#/anti-browser', {waitUntil: 'networkidle0'});
    
    // Open drawer
    await page.evaluate(() => {
        document.querySelector('button[title="New Profile"]')?.click();
        // The header button has no title, let's find by text
        Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('New Profile'))?.click();
    });
    
    // Wait for drawer
    await new Promise(r => setTimeout(r, 500));
    
    // Select Camoufox
    await page.evaluate(() => {
        const select = document.querySelector('select[x-model="antiBrowser.form.plugin"]');
        select.value = 'camoufox';
        select.dispatchEvent(new Event('change'));
    });
    
    await new Promise(r => setTimeout(r, 500));
    
    // Check if install button is visible and active
    const btn = await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('Install Now'));
        if (!b) return null;
        return { disabled: b.disabled, text: b.textContent, outerHTML: b.outerHTML };
    });
    console.log("Button state:", btn);
    
    // Try click
    await page.evaluate(() => {
        const b = Array.from(document.querySelectorAll('button')).find(el => el.textContent.includes('Install Now'));
        if (b) b.click();
    });
    
    await new Promise(r => setTimeout(r, 500));
    await browser.close();
})();

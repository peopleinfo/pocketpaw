import { chromium } from "playwright";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log("Navigating...");
  await page.goto("http://localhost:5173/");

  console.log("Opening Test Project...");
  try {
    await page.click("text=Test Project");
    await page.waitForTimeout(2000);
  } catch (e) {
    console.log("Could not find Test Project, using URL directly");
    await page.waitForTimeout(2000);
  }

  // Clear existing items in timeline if possible by double-clicking timeline and hitting delete
  // (Assuming there was some messy state, or we just upload and append)

  console.log("Uploading file...");
  const fileChooserPromise = page.waitForEvent("filechooser");
  await page.locator("input[type=file]").dispatchEvent("click");
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles("C:/Users/dila/Downloads/test_60s_nvenc.mp4");

  await page.waitForTimeout(2000);

  console.log("Adding to timeline...");
  // Assuming the UI has an "Add to timeline" button
  await page.click('[aria-label="Add to timeline"]');
  await page.waitForTimeout(1000);

  console.log("Clicking Export menu...");
  await page.click('button:has-text("Export")');
  await page.waitForTimeout(500);

  console.log("Clicking Export Video...");
  // Look for the "Export Video" menu item
  await page.click('div[role="menuitem"]:has-text("Export Video")');
  await page.waitForTimeout(1000);

  console.log("Starting Render...");
  // In the modal, find the second Export Video button
  await page.click('button:has-text("Export Video")');

  console.log("Waiting for completion...");
  await page.waitForSelector("text=Export complete!", { timeout: 120000 });

  console.log("Capturing screenshot...");
  await page.screenshot({
    path: "C:/Users/dila/.gemini/antigravity/brain/cd74c081-774a-48f1-8c04-ca66a4197869/artifacts/export_1min_speed_test.png",
  });

  await browser.close();
  console.log("Done");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});

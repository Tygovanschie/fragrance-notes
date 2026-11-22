# Fragrance Notes

A browser extension that shows what a perfume smells like while you shop. On a perfume product page it adds a small 🌸 button; click it for the perfume's notes, accords, longevity, sillage, when to wear it, pros & cons and similar perfumes — all from [Fragrantica](https://www.fragrantica.com).

Website: https://fragrancenotes.app

Data from Fragrantica. Not affiliated with Fragrantica.

## Install

- **Chrome Web Store:** https://chromewebstore.google.com/detail/fragrance-notes/hhhiolpcmkdkegcmjmpglcnfolohldgc?hl=en-US.
- **By hand:** open `chrome://extensions`, turn on *Developer mode*, choose *Load unpacked* and select this folder.

Works in Chrome, Edge, Brave, Opera, Vivaldi and Arc (version 102 or newer).

## Using it

1. Open a perfume on a shop such as Douglas, Notino, Sephora, Skins or De Bijenkorf.
2. A 🌸 button appears in the corner. A green dot on it means the results are ready.
3. Click it to open the panel:
   - **Summary:** rating, longevity, sillage and the best seasons.
   - **Main accords** and the **notes pyramid** (click a note for its scent description).
   - **When to wear**, **pros & cons** and the **votes** (click a line for all votes).
   - **Prices** for each size on this shop. With price sharing on: how each size compares with other shops in your country, and the lowest price in the last 30 days.
   - **Reminds people of** and **cheaper alternatives (dupes)**.

The toolbar menu (click the extension icon) shows the perfume on the current page, lets you look up any perfume, turns the extension on or off, and adds the current site if it isn't supported yet.

## Settings

Right-click the icon → *Options*, or use the gear in the panel or menu.

- **General:** language (any of Fragrantica's 23 languages), automatic search, open on click or automatically, keyboard shortcut.
- **Look:** colour theme (Plum, Iris, Amber, Minimal — each light and dark, or automatic), Rich or Simple style, accords as bars or a colour strip.
- **Panel:** corner and size.
- **What to show:** turn each part of the panel on or off.
- **Shops:** add a missing shop, or let the extension work on every website.
- **Data:** turn anonymous price sharing on or off, clear saved results, or reset all settings.

## Privacy

The extension reads the perfume name and prices on shop product pages, looks the perfume up on Bing and Fragrantica, and saves results locally for 14 days. There is no account, tracking or advertising.

Price sharing is off until you turn it on. Then only the perfume, size, price and shop are sent to the Fragrance Notes price server, with a random install ID and nothing about you. See the [privacy policy](PRIVACY.md).

## What's new in 1.2

- Works in Firefox and Edge as well as Chrome.
- A close button (×) in the panel header, and Esc closes the panel.
- Cleaner When to wear section and more room in the summary tiles.
- A one-time request for a store review in the toolbar menu, after you've looked up 10 perfumes. It's only a count kept in your browser.

## What's new in 1.1

- **Compare prices (optional):** with anonymous price sharing on, each size shows how its price compares with other shops in your country (Great deal, Fair price or Overpriced), where it's cheapest, and the lowest price in the last 30 days.
- **More shops and countries:** niche perfume shops such as Jovoy, Nose, Santa Maria Novella and 24S, and US shops with sizes in fl oz.
- **Better price reading:** every size, also ones behind "show all sizes" or a size menu; no more prices from recommended products, instalment plans or samples.
- **New look:** the fonts and style of [fragrancenotes.app](https://fragrancenotes.app) in the panel, menu and settings, and a welcome page after installing.

## Making the store zip

Run `make-zip.ps1` in PowerShell. It builds `fragrance-notes-<version>.zip` next to this folder from an explicit list of files, so notes, the website (`site/`) and the server (`server/`) never end up in it.

## License

[MIT](LICENSE) © 2026 Tygo van Schie. Perfume data belongs to Fragrantica and is not covered by this license.

## Firefox and Edge (1.2)

One folder works in Chrome, Edge and Firefox. The manifest lists the background script twice:
`service_worker` for Chrome and Edge, `scripts` for Firefox (each browser ignores the other one), and
`browser_specific_settings.gecko` holds the Firefox add-on ID and its data-collection declaration.

- Test in Firefox: open `about:debugging#/runtime/this-firefox` → *Load Temporary Add-on…* → pick `manifest.json`.
- Check before uploading to Firefox: `npx addons-linter fragrance-notes-<version>.zip` (expect 0 errors;
  the service_worker and innerHTML warnings are fine).
- The same zip from `make-zip.ps1` goes to the Chrome Web Store, Edge Add-ons and addons.mozilla.org.
- After the Edge listing is approved: add its ID to REVIEW_URL in settings.js and to the server's ALLOWED_ORIGINS.

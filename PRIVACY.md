# Fragrance Notes – Privacy policy

Last updated: 22 November 2026 (version 1.1)

Fragrance Notes is a browser extension that shows information from Fragrantica about the perfume you are looking at in a web shop. This policy explains what the extension reads, where it sends it and what it stores.

## What the extension reads

On perfume product pages of supported shops (and shops you add yourself), the extension reads the product name, brand, and the sizes and prices shown on the page. It does not read other pages, forms, passwords or payment details.

## Where information is sent

- **Bing** (bing.com): the perfume name is searched to find the matching Fragrantica page.
- **Fragrantica** (fragrantica.com and its language sites, and fimgs.net for pictures): the perfume's page, note pages and search are opened to read the perfume's details.

These requests go directly from your browser to those websites, just as when you visit them yourself, and are covered by their own privacy policies.

Unless you turn on **Share prices anonymously**, nothing is sent to the developer of Fragrance Notes.

## Share prices anonymously (optional, off by default)

You can turn this on under Settings → Data. While it is on:

- **What is sent** to the Fragrance Notes price server, for each size on a product page of a *built-in* shop:
  the Fragrantica perfume number (for example 9828), the size in ml, the price, the currency and the shop's domain (for example douglas.nl).
  With it goes a random install ID that the extension creates when you turn sharing on.
- **What is not sent:** page addresses, your search terms, your name, e-mail, account or any other personal details. Prices from shops you added yourself are never shared.
- **What you get back:** for the perfume you are looking at, the extension asks the server for the prices other users shared in the last 30 days (median, lowest and highest price per ml, and the cheapest shops). This request contains only the perfume number and currency.
- **On the server:** the install ID is only stored as a salted hash, used to limit how often one install can send prices and to keep one price per install, perfume, shop and size. IP addresses are not stored or logged by the server. Shared prices are deleted after 90 days.
- **Connection:** the server runs on the developer's own machine and is reached over HTTPS at api.fragrancenotes.app through Cloudflare. Like for any website that uses Cloudflare, Cloudflare handles the connection on its way to the server: it can see your IP address and the request itself (the perfume number, sizes, prices, shop and install ID described above), and processes this under its own privacy policy (cloudflare.com/privacypolicy). The server itself does not store or log IP addresses.
- **Turning it off** stops all sending and deletes the install ID from your browser. If you turn it on again, you get a new install ID that cannot be linked to the old one. Prices shared earlier stay on the server, without anything that identifies you, until they expire after 90 days.

Shared prices are only used to show price information to users of Fragrance Notes. They are not sold and not shared with anyone else.

## What is stored

In your own browser:

- your settings and the shops you added (synced by your browser if you use browser sync);
- a count of how many perfumes you have looked up, used only to ask once for a store review;
- looked-up perfume results, kept for 14 days;
- prices you saw on shop pages, kept for 90 days, to show prices at other shops;
- if sharing is on: the random install ID, and for one day a list of the prices already sent, so they are not sent twice.

You can delete saved results at any time under Settings → Data, or by removing the extension.

On the Fragrance Notes price server (only if you turned sharing on): the shared prices described above, for 90 days.

## What the extension does not do

No account, no analytics, no tracking, no advertising. Your data is not sold, shared or used for any other purpose.

## Changes

If this policy changes, the new version will be posted here with a new date. Earlier versions stay visible in this file's history.

## Contact

Questions? Open an issue at https://github.com/Tygovanschie/fragrance-notes/issues

Fragrance Notes is an independent project and is not affiliated with or endorsed by Fragrantica.

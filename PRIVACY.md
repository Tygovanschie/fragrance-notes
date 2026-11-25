# Fragrance Notes – Privacy policy

Last updated: 25 November 2026 (version 1.4)

Fragrance Notes is a browser extension that shows information from Fragrantica about the perfume you are looking at in a web shop. This policy explains what the extension reads, where it sends it and what it stores.

## What the extension reads

On perfume product pages of supported shops (and shops you add yourself), the extension reads the product name, brand, concentration, barcode, whether it is for men or women, the sizes and prices, and the notes and fragrance family the shop lists. It does not read other pages, forms, passwords or payment details.

## Where information is sent

- **Bing** (bing.com): the perfume name is searched to find the matching Fragrantica page.
- **Fragrantica** (fragrantica.com and its language sites, and fimgs.net for pictures): the perfume's page, note pages and search are opened to read the perfume's details.
- **The Fragrance Notes database** (api.fragrancenotes.app): on a product page, the extension asks whether the open perfume database knows this perfume, so it can show notes that several shops confirmed. The question contains only the brand, name, concentration, men/women and barcode shown on the page; no install ID, page address or anything about you. The server answers and does not store or log the question (it passes through Cloudflare, see below).

The requests to Bing and Fragrantica go directly from your browser to those websites, just as when you visit them yourself, and are covered by their own privacy policies.

Apart from that anonymous question, nothing is sent to the developer of Fragrance Notes unless you turn on **Help other perfume lovers** (Settings → Data). That one setting covers both kinds of sharing described below: prices, and perfume facts for the open perfume database. The extension asks once, on the welcome page, whether you want to help (nothing is on until you say yes); if you never answer, it may ask once more in the panel and once in the toolbar menu.

## Sharing prices (part of Help other perfume lovers, off by default)

While **Help other perfume lovers** is on:

- **What is sent** to the Fragrance Notes price server, for each size on a product page of a *built-in* shop:
  the Fragrantica perfume number (for example 9828), the size in ml, the price, the currency and the shop's domain (for example douglas.nl).
  With it goes a random install ID that the extension creates when you turn sharing on.
- **What is not sent:** page addresses, your search terms, your name, e-mail, account or any other personal details. Prices from shops you added yourself are never shared.
- **What you get back:** for the perfume you are looking at, the extension asks the server for the prices other users shared in the last 30 days (median, lowest and highest price per ml, and the cheapest shops). This request contains only the perfume number and currency.
- **On the server:** the install ID is only stored as a salted hash, used to limit how often one install can send prices and to keep one price per install, perfume, shop and size. IP addresses are not stored or logged by the server. Shared prices are deleted after 90 days.
- **Connection:** the server runs on the developer's own machine and is reached over HTTPS at api.fragrancenotes.app through Cloudflare. Like for any website that uses Cloudflare, Cloudflare handles the connection on its way to the server: it can see your IP address and the request itself (the perfume number, sizes, prices, shop and install ID described above), and processes this under its own privacy policy (cloudflare.com/privacypolicy). The server itself does not store or log IP addresses.
- **Turning the setting off** stops all sending and deletes the install ID from your browser. If you turn it on again, you get a new install ID that cannot be linked to the old one. Prices shared earlier stay on the server, without anything that identifies you, until they expire after 90 days.

Shared prices are only used to show price information to users of Fragrance Notes. They are not sold and not shared with anyone else.

## Building the open perfume database (part of Help other perfume lovers, off by default)

While **Help other perfume lovers** is on, on a perfume product page of a *built-in* shop:

- **What is sent** to the Fragrance Notes server: the facts the shop shows about that perfume. That is the brand, the name, the concentration (for example Eau de Parfum), the sizes, the barcode (EAN) if the shop includes it, the top, heart and base notes and fragrance family if the shop lists them, whether it is sold for men, women or both, the page's language, and the shop's domain. If the panel found the perfume on Fragrantica, its Fragrantica number goes with it to link the facts to the right perfume. With it goes the same random install ID as for price sharing.
- **What is not sent:** page addresses, prices, your search terms, your name, e-mail, account or any other personal details. Pages of shops you added yourself are never used.
- **On the server:** the install ID is only stored as a salted hash, used to limit how much one install can send and to keep one report per install, shop and perfume a day. After 90 days the hash is replaced by a random value, so older facts can't be linked to each other or to an install. IP addresses are not stored or logged by the server. The facts themselves are kept: they are combined with facts from other users and other open sources into an open perfume database, published under the Open Database License (ODbL), so anyone may use it. They contain nothing about you.
- **Shops you added yourself:** the domain names of shops you added yourself in Settings (for example armani.com, never a page address) are sent once, with the install ID, so shops that many people add can be reviewed and added to the built-in list. Their prices and product facts are still never shared. On the server each domain is stored with the install hash, which is replaced by a random value after 90 days.
- **What you see back:** the toolbar menu shows how many notes your shared facts helped confirm. To count them, it sends the install ID to the server, which only reads the facts you shared in the last 90 days and stores nothing about this request.
- **Connection:** the same as for price sharing (through Cloudflare, see above).
- **Turning the setting off** stops this too (see above).

## Voting on fragrancenotes.app (website only)

The perfume pages on fragrancenotes.app let you rate a perfume (stars, longevity, sillage, value for money and who it is for). Voting is optional and needs no account.

- **What is sent:** your answers, and that you ticked "I own this perfume or have worn it".
- **Cookie:** when you vote, the site stores one cookie, `fn_voter`, with a random code, so you have one vote per perfume and can change it. It is set only when you vote, contains nothing about you, and expires after a year. Without it you can still read everything.
- **On the server:** your answers per perfume and a salted hash of the code, never the code itself. After a year the hash is replaced by a random value. Your IP address is used only in memory to limit how many votes can be sent at once, and is not stored or logged.
- **What is shown:** only totals (averages and how many people chose each answer), and only once at least 3 people voted on that perfume.

## What is stored

In your own browser:

- your settings and the shops you added (synced by your browser if you use browser sync);
- your favourites: for each perfume its name, Fragrantica address and picture address (synced by your browser if you use browser sync);
- your price alerts: for each favourite with an alert, the size and the price you set (synced by your browser if you use browser sync). While sharing is on, the extension checks them every six hours with the same anonymous price request as above (only the perfume number and currency), and shows a notification if you allowed notifications;
- a count of how many perfumes you have looked up, used only to ask once for a store review and once whether you want to share;
- whether you already answered those questions;
- looked-up perfume results, kept for 14 days;
- prices you saw on shop pages, kept for 90 days, to show prices at other shops;
- if sharing is on: the random install ID, and for one day a list of the prices already sent, so they are not sent twice.

You can delete saved results at any time under Settings → Data, or by removing the extension.

On the Fragrance Notes server, only if you turned the matching setting on: the shared prices described above, for 90 days; and the perfume facts described above, which are kept as part of the open perfume database (their install hash is replaced after 90 days).

## What the extension does not do

No account, no analytics, no tracking, no advertising. Your data is not sold, shared or used for any other purpose.

## Changes

If this policy changes, the new version will be posted here with a new date. Earlier versions stay visible in this file's history.

## Contact

Questions? Open an issue at https://github.com/Tygovanschie/fragrance-notes/issues

Fragrance Notes is an independent project and is not affiliated with or endorsed by Fragrantica.

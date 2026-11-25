"""The open perfume database: built from the product facts that users share (POST /facts).

Every rebuild (see app.catalog_loop) does three things, all with the standard library:

1. Clean up: brand and name are compared as "keys" without case, accents, punctuation, the brand's own
   words ("Emporio Armani Stronger With You" at one shop is "Stronger With You" at another) or filler
   words. Brand spellings are merged ("Yves Saint Laurent" = "YSL", "Christian Dior" = "Dior").
2. Match: facts become one perfume when they share brand + name + concentration (+ men/women when a
   shop says so), or the same barcode. A fact with no concentration, or no men/women, joins the single
   concentration or men's/women's version if there is exactly one.
3. Combine: every value counts the distinct shops that state it. A note, family or men/women value is
   "confirmed" once CONFIRM_SHOPS different shops agree; one shop alone can be wrong (Douglas, for
   example, sometimes shows two different note lists for one perfume). Perfumes with contradictions
   are flagged for review.

Open Beauty Facts (obf.py) is read as one more source: barcodes, brands, names and sizes, no notes.

Notes are compared in the language the shop wrote them in ("Ceder" and "Cedar" are still two notes);
translating them to one name is a later step.

The result is the table `catalog`, published under the Open Database License (ODbL) when exported.
"""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict

import obf

CONFIRM_SHOPS = 2

# Brand spellings that mean the same house. Keys and values are normalised brand keys (see brand_key).
BRAND_ALIASES = {
    "giorgio armani": "armani", "emporio armani": "armani", "armani prive": "armani", "ea": "armani",
    "armani beauty": "armani",
    "yves saint laurent": "ysl", "saint laurent": "ysl",
    "christian dior": "dior", "maison christian dior": "dior",
    "rabanne": "paco rabanne",
    "boss": "hugo boss", "hugo": "hugo boss",
    "maison francis kurkdjian": "mfk", "francis kurkdjian": "mfk",
    "dolce gabbana": "dolce gabbana", "d g": "dolce gabbana",
    "jean paul gaultier": "jpg", "gaultier": "jpg",
    "calvin klein": "ck",
    "viktor rolf": "viktor rolf",
    "ralph lauren": "ralph lauren", "polo ralph lauren": "ralph lauren",
    "lancome": "lancome",
    "narciso rodriguez": "narciso rodriguez",
    "carolina herrera": "carolina herrera",
    "tom ford": "tom ford", "tom ford private blend": "tom ford",
}
# Words in a brand name that don't tell houses apart.
BRAND_FILLER = {"parfums", "parfum", "perfumes", "perfume", "paris", "fragrances", "fragrance", "cosmetics",
                "beauty", "les", "de", "the", "and", "et"}
# Gender words in a name, folded to one form so "Pour Homme" and "for Men" match.
MALE_WORDS = {"homme", "hommes", "men", "man", "him", "uomo", "hombre", "herren", "heren", "mannen"}
FEMALE_WORDS = {"femme", "femmes", "women", "woman", "her", "donna", "mujer", "damen", "dames", "vrouwen"}
NAME_FILLER = {"pour", "for", "voor", "fur", "per", "para", "spray", "vapo", "vaporisateur", "natural", "the"}
# Promotion and packaging words that shops put behind the name ("Stronger With You Intensely - Summer Deal",
# "Libre - Rechargeable", "Bleu Byzantin (Travel)"). Without a barcode they would split one perfume in two, so
# name_key ignores them at the end of a name, and the displayed name drops them.
PROMO_TAIL = re.compile(r"[\s,]*[-–(\[/]?\s*\b(?:summer deal|winter deal|black friday deal|deal|actie|aanbieding|"
                        r"rechargeable|refillable|refill|recharge|navulbaar|nachfullbar|nachfüllbar|"
                        r"travel(?: size| spray| edition)?|new in box|brand new|tester|gift ?set|coffret|"
                        r"parf[uü]m(?:[uü])? seti|seti)\b\s*[)\]]?\s*$", re.I)
# Sub-brand words that shops leave in front of the name without the house itself ("Emporio Stronger With You",
# "Giorgio Stronger With You", "EA STRONGER WITH YOU"); the displayed name leaves them out. Only these: in
# "Armani Code", "Narciso Poudrée" or "Cerruti 1881 Black" the house word is part of the perfume's name.
ORPHAN_PREFIX = {"armani": {"emporio", "giorgio", "ea"}}


def strip_promo(name):
    """"Libre - Rechargeable" -> "Libre"; repeated for "… Refillable - Summer Deal". Never empties a name."""
    s = str(name or "")
    while (t := PROMO_TAIL.sub("", s).strip()) != s and re.search(r"\w", t):
        s = t
    return s
# Product words that are no name on their own ("WhatsApp Perfume" stays, not "Perfume").
PRODUCT_WORDS = {"perfume", "perfumes", "parfum", "parfume", "fragrance", "cologne", "kolonya", "deodorant", "deo",
                 "body", "mist", "spray", "eau", "edp", "edt", "edc"}
NOTE_FILLER = {"accord", "accoord", "akkoord", "akkord", "accordo", "acorde", "note", "notes", "noot", "noten",
               "accords", "akkoorden", "geurnoot", "geurnoten", "notities", "nuances", "facetten", "touch", "vleugje"}
# Words that describe a note without making it another note: "Transparant Frangipani Akkoord", "Indiase
# Patchouli", "Italiaanse Bergamot", "Zachte Muskus" are frangipani, patchouli, bergamot and musk. (Words that do
# make another note, like "roze" peper or "witte" musk, are in NOTE_WORDS as their own note.)
NOTE_DESCRIPTORS = {
    "transparant", "transparante", "transparent", "transparente", "zacht", "zachte", "soft", "fris", "frisse",
    "licht", "lichte", "light", "donker", "donkere", "dark", "warm", "warme", "sensueel", "sensuele", "sensual",
    "romig", "romige", "creamy", "rijk", "rijke", "rich", "edel", "edele", "kostbaar", "kostbare", "precious",
    "natuurlijk", "natuurlijke", "natural", "verse", "vers", "zonnig", "zonnige", "sprankelend", "sprankelende",
    "sparkling", "bruisend", "bruisende", "intens", "intense", "diep", "diepe", "deep", "levendig", "levendige",
    "italiaans", "italiaanse", "italian", "calabrisch", "calabrische", "calabrian", "siciliaans", "siciliaanse",
    "sicilian", "indiaas", "indiase", "indian", "indonesisch", "indonesische", "indonesian", "haitiaans",
    "haitiaanse", "haitian", "bulgaars", "bulgaarse", "bulgarian", "turks", "turkse", "turkish", "egyptisch",
    "egyptische", "egyptian", "marokkaans", "marokkaanse", "moroccan", "toscaans", "toscaanse", "tuscan",
    "florentijns", "florentijnse", "madagaskar", "madagascar", "mexicaans", "mexicaanse", "mexican", "tahitiaans",
    "tahitiaanse", "tahitian", "virginia", "atlas", "provencaals", "provencaalse", "frans", "franse", "french",
    "absolue", "absolute", "essentie", "essence", "extract", "olie", "oil", "huile", "infusie", "infusion",
    "bloem", "bloemen", "flower", "flowers", "blad", "bladeren", "leaf", "leaves",
    "pure", "puur", "absoluut", "absolu", "echte", "echt", "real", "arabische", "arabisch", "arabian", "australisch",
    "australische", "australian", "blauwe", "blauw", "exclusief", "exclusieve", "geroosterde", "geroosterd",
    "roasted", "gekarameliseerde", "gekarameliseerd", "caramelized", "vulkanische", "vulkanisch", "volcanic",
    "venezolaanse", "venozolaanse", "xxl", "uit", "amalfi", "leerachtige", "leerachtig", "maritiem", "maritieme",
    "grand", "vert", "zand", "coeur", "kostbare", "essences", "houtachtige", "houtachtig", "sensuele", "witte",
}
# Things shops list as a note that aren't one ("Bovenlichaam" from a description, a lone "Noot").
NOTE_JUNK = {"bovenlichaam", "lichaam", "huid", "skin", "body", "geur", "scent", "parfum", "perfume", "fragrance"}
# Words in front of a note that don't change it: "compositie van zure kersen" (Notino) = "zure kersen".
NOTE_PREFIX = re.compile(r"^(?:compositie|composition|trio|duo|combinatie|combination|melange|mix|blend|accord|akkoord|akkord)"
                         r"(?: (?:van|of|de|d|di|von|aus))? ")

# One note in several languages, so shops in different languages confirm each other ("Kastanjes" at Douglas,
# "Kastanje" at Notino, "Chestnut" in English). Variants are written as plain() makes them (lowercase, no accents)
# and without NOTE_FILLER words. Only real translations: "geglazuurde kastanje" (glazed chestnut) stays its own note.
# Fragrance families use the same table (Douglas "Kruidig", Notino "specerijen").
NOTE_WORDS = """
vanilla: vanille | vanilla | vainilla | vaniglia | baunilha | wanilia
tonka bean: tonkaboon | tonka boon | tonkabonen | tonka bonen | tonka | tonkabohne | tonka bohne | feve tonka | feve de tonka | haba tonka | fava tonka | tonka bean | tonka beans
chestnut: kastanje | kastanjes | chestnut | chestnuts | kastanie | kastanien | chataigne | marron | castana | castagna
glazed chestnut: geglazuurde kastanje | geglazuurde kastanjes | gekristalliseerde kastanje | gekristalliseerd kastanje | glazed chestnut | glazed chestnuts | marron glace | marrons glaces | kandierte kastanie | castagna candita
bourbon vanilla: bourbon vanille | bourbonvanille | bourbon vanilla | vanille bourbon | vanilla bourbon | vainilla bourbon
frangipani: frangipani | frangipanier | plumeria | frangipane bloem
lavender: lavendel | lavender | lavande | lavanda
cinnamon: kaneel | cinnamon | zimt | cannelle | canela | cannella
sage: salie | sage | salbei | sauge | salvia
pepper: peper | peperkorrel | peperkorrels | pepper | peppercorn | peppercorns | pfeffer | poivre | pimienta | pepe | pimenta
pink pepper: roze peper | roze peperkorrel | roze peperkorrels | pink pepper | pink peppercorn | pink peppercorns | rosa pfeffer | rosa pepper | baies roses | poivre rose | pimienta rosa | pepe rosa
black pepper: zwarte peper | black pepper | schwarzer pfeffer | poivre noir | pimienta negra | pepe nero
cardamom: kardemom | kardemon | cardamom | kardamom | cardamome | cardamomo
juniper: jeneverbes | jeneverbessen | jenever | jeneverstruik | juniper | juniper berry | juniper berries | wacholder | wacholderbeere | genievre | baies de genievre | enebro | ginepro
ginger: gember | ginger | ingwer | gingembre | jengibre | zenzero
bergamot: bergamot | bergamotte | bergamota | bergamotto
lemon: citroen | lemon | zitrone | citron | limon | limone
mandarin: mandarijn | mandarin | mandarine | mandarina | mandarino
orange: sinaasappel | oranje | orange | naranja | arancia
grapefruit: grapefruit | pompelmoes | pamplemousse | pomelo | pompelmo
apple: appel | apple | apfel | pomme | manzana | mela
pear: peer | pear | birne | poire | pera
peach: perzik | peach | pfirsich | peche | melocoton | pesca
cherry: kers | kersen | cherry | cherries | kirsche | kirschen | cerise | cereza | ciliegia
sour cherry: zure kers | zure kersen | sour cherry | sour cherries | sauerkirsche | griotte | guinda | amarena
blackcurrant: zwarte bes | zwarte bessen | blackcurrant | black currant | cassis | schwarze johannisbeere | grosella negra | ribes nero
raspberry: framboos | frambozen | raspberry | himbeere | framboise | frambuesa | lampone
pineapple: ananas | pineapple | pina
coconut: kokos | kokosnoot | kokoshout | coconut | kokosnuss | noix de coco | coco | cocco
passion fruit: passievrucht | maracuja | passion fruit | passionsfrucht | fruit de la passion | fruta de la pasion | frutto della passione
rose: roos | rozen | rose | roses | rosa | rosen
jasmine: jasmijn | jasmine | jasmin | jazmin | gelsomino
orange blossom: oranjebloesem | oranje bloesem | oranjebloem | sinaasappelbloesem | sinaasappelboom bloesem | orange blossom | orangenblute | orangenbluete | fleur d oranger | azahar | fiori d arancio | fiore d arancio
tuberose: tuberoos | tuberose | tuberosa | tubereuse
violet: viooltje | viooltjes | violet | veilchen | violette | violeta | violetta
lily of the valley: lelietje van dalen | lily of the valley | maiglockchen | muguet | lirio de los valles | mughetto
patchouli: patchoeli | patchouli | pachuli | patchouly | patchuli | pathouli
vetiver: vetiver | vetivert | vetyver
sandalwood: sandelhout | sandalwood | sandelholz | bois de santal | santal | sandalo
cedar: ceder | cederhout | cedar | cedarwood | zeder | zedernholz | cedre | bois de cedre | cedro
oud: oud | oudh | agarwood | oudhout | adlerholz | bois d oud
amber: amber | barnsteen | ambra | ambre | ambar
musk: muskus | musk | moschus | musc | almizcle | muschio
leather: leer | leren | leather | leder | cuir | cuero | cuoio
tobacco: tabak | tabaksbladeren | tabaksblad | tobacco | tabac | tabaco | tabacco
honey: honing | honey | honig | miel | miele
caramel: karamel | caramel | karamell | caramelo | caramello
coffee: koffie | coffee | kaffee | cafe | caffe
cocoa: cacao | cocoa | kakao
chocolate: chocolade | chocolate | schokolade | chocolat | cioccolato
almond: amandel | almond | mandel | amande | almendra | mandorla
benzoin: benzoe | benzoine | benzoin | benjoin | benjui | benzoino
incense: wierook | incense | weihrauch | encens | incienso | incenso
myrrh: mirre | myrrh | myrrhe | mirra
oakmoss: eikenmos | eiken mos | eikmos | oakmoss | oak moss | eichenmoos | mousse de chene | musgo de roble | muschio di quercia
mint: munt | mint | mintachtig | minty | minze | menthe | menta
violet leaf: viooltjesblad | viooltjesbladeren | vioolblaadjes | vioolblad | violet leaf | violet leaves | veilchenblatt | veilchenblatter | feuille de violette | feuilles de violette | hoja de violeta | foglia di violetta
toffee: toffee | karamelsnoep
suede: suede | daim | wildleder | gamuza | camoscio
melon: meloen | melon | melone
guaiac wood: guaiac hout | guaiachout | guaiac wood | guajakholz | bois de gaiac | gaiac | guayaco | guaiaco
amberwood: amberhout | amberwood | amber wood | bois ambre | bois ambres
basil: basilicum | basil | basilikum | basilic | albahaca | basilico
rosemary: rozemarijn | rosemary | rosmarin | romarin | romero | rosmarino
geranium: geranium | geranie | geranio
tea: thee | tea | tee | the | te
saffron: saffraan | saffron | safran | azafran | zafferano
clove: kruidnagel | kruidnagels | clove | cloves | nelke | gewurznelke | clou de girofle | clavo | chiodi di garofano
nutmeg: nootmuskaat | nutmeg | muskatnuss | noix de muscade | nuez moscada | noce moscata
maple syrup: ahornsiroop | maple syrup | ahornsirup | sirop d erable | jarabe de arce | sciroppo d acero
iris: iris | irissen | irisbloem | iriswortel | orris | orriswortel | orris root | iris pallida | racine d iris | iriswurzel | giaggiolo
neroli: neroli | neroliolie | neroli oil | neroli bigarade
petitgrain: petitgrain | petit grain
ylang ylang: ylang ylang | ylang | ilang ilang | ylangylang
magnolia: magnolia | magnolie
peony: pioen | pioenroos | pioenrozen | peony | peonies | pfingstrose | pivoine | peonia
freesia: fresia | freesia | freesie
lily: lelie | lelies | lily | lilies | lilie | lis | lys | giglio
water lily: waterlelie | water lily | nenuphar | seerose | ninfea
lotus: lotus | lotusbloem | lotusblume | loto
gardenia: gardenia | gardenie
osmanthus: osmanthus | osmanthe | osmanto
mimosa: mimosa | mimose
lilac: sering | seringen | lilac | flieder | lilas | lila
hyacinth: hyacint | hyacinth | hyazinthe | jacinthe | jacinto | giacinto
narcissus: narcis | narcissen | narcissus | narzisse | narcisse | narciso
orchid: orchidee | orchideeen | orchid | orchidee noire | orquidea | orchidea
honeysuckle: kamperfoelie | honeysuckle | geissblatt | chevrefeuille | madreselva | caprifoglio
heliotrope: heliotroop | heliotrope | heliotrop | heliotropo
carnation: anjer | anjers | carnation | oeillet | clavel | garofano
cyclamen: cyclaam | cyclamen | alpenveilchen
champaca: champaca | champak
ambrette: ambrette | ambrettezaad | muskuszaad | ambrette seed | graine d ambrette
lime: limoen | limoenen | lime | limette | citron vert | lima | limetta
yuzu: yuzu
bitter orange: bittere sinaasappel | bitter orange | bigarade | bitterorange | orange amere | naranja amarga | arancia amara
blood orange: bloedsinaasappel | tarocco sinaasappel | tarocco | blood orange | blutorange | orange sanguine | naranja sanguina | arancia rossa
blood mandarin: bloed mandarijn | bloedmandarijn | blood mandarin | mandarine sanguine
clementine: clementine | clementina
lemon verbena: citroenverbena | verbena | lemon verbena | verveine | zitronenverbene | verbena de limon
lemongrass: citroengras | lemongrass | zitronengras | citronnelle | hierba limon
fig: vijg | vijgen | vijgenblad | fig | fig leaf | feige | figue | higo | fico
banana: banaan | banana | banane
mango: mango | mangue
lychee: lychee | litchi | lychees
blackberry: braam | bramen | blackberry | brombeere | mure | mora
strawberry: aardbei | aardbeien | strawberry | erdbeere | fraise | fresa | fragola
apricot: abrikoos | abrikozen | apricot | aprikose | abricot | albaricoque | albicocca
plum: pruim | pruimen | plum | plums | pflaume | prune | ciruela | prugna
quince: kwee | kweepeer | quince | quitte | membrillo | mela cotogna
rhubarb: rabarber | rhubarb | rhabarber | rhubarbe | ruibarbo | rabarbaro
red berries: rode bessen | rode vruchten | red berries | red fruits | rote beeren | fruits rouges | frutos rojos | frutti rossi
nectarine: nectarine | nektarine | nectarina
pomegranate: granaatappel | pomegranate | granatapfel | grenade | granada | melograno
cucumber: komkommer | cucumber | gurke | concombre | pepino | cetriolo
pistachio: pistache | pistachenoot | pistachio | pistazie | pistacho | pistacchio
hazelnut: hazelnoot | hazelnoten | hazelnut | haselnuss | noisette | avellana | nocciola
praline: praline | pralines | pralinee
marshmallow: marshmallow | spekje | spekjes | guimauve
sugar: suiker | sugar | zucker | azucar | zucchero
milk: melk | milk | milch | lait | leche | latte
cream: room | slagroom | cream | sahne | creme | crema | panna
licorice: drop | zoethout | licorice | liquorice | lakritz | reglisse | regaliz | liquirizia
rum: rum | rhum | ron
cognac: cognac | brandy
whiskey: whisky | whiskey
wine: wijn | wine | wein | vin | vino
champagne: champagne
anise: anijs | anise | anis | anice
star anise: steranijs | star anise | sternanis | badiane | anis estrellado | anice stellato
coriander: koriander | coriander | coriandre | cilantro | coriandolo
cumin: komijn | cumin | kreuzkummel | comino
caraway: karwij | karwijzaad | caraway | kummel | carvi | alcaravea
tarragon: dragon | tarragon | estragon | artemisia dracunculus | dragoncello
thyme: tijm | thyme | thymian | thym | tomillo | timo
bay leaf: laurier | laurierblad | bay leaf | laurel | lorbeer | alloro
clary sage: scharlei | muskaatsalie | clary sage | sauge sclaree | muskatellersalbei | salvia sclarea
davana: davana
wormwood: alsem | absint | wormwood | absinthe | wermut | ajenjo | assenzio
elemi: elemi
galbanum: galbanum
frankincense: olibanum | frankincense | weihrauchharz | encens oliban
labdanum: labdanum | ladanum | cistus labdanum | cistus | ciste | cistrose
resin: hars | harsen | resin | resins | harz | resine | resina
ambergris: ambergris | grijze amber | ambre gris | amber gris | ambra grigia | ambar gris
ambroxan: ambroxan | ambrox | ambroxide | ambrofix | ambrofixtm
cashmeran: cashmeran | kasjmierhout | cashmere wood | bois de cachemire | kaschmirholz
iso e super: iso e super
hedione: hedione
aldehydes: aldehyden | aldehyde | aldehydes | aldeidi
white musk: witte musk | witte muskus | white musk | weisser moschus | musc blanc | almizcle blanco | muschio bianco
civet: civet | civette | zibet | zibetone
castoreum: castoreum | bevergeil
birch: berk | berkenhout | berkenteer | birch | birch tar | birke | bouleau | abedul | betulla
cypress: cipres | cypress | zypresse | cypres | cipresso
pine: den | dennen | dennennaald | dennennaalden | pine | pine needles | kiefer | pin | pino
fir: spar | sparrenhout | vurenhout | zilverspar | fir | balsam fir | tanne | sapin | abeto | abete
oak: eik | eikenhout | oak | oakwood | eiche | chene | roble | quercia
mahogany: mahonie | mahoniehout | mahogany | mahagoni | acajou | caoba | mogano
rosewood: palissander | rozenhout | rosewood | rosenholz | bois de rose | palisandro
ebony: ebbenhout | ebbehout | ebony | ebenholz | ebene | ebano
olive tree: olijfboom | olijf | olijfhout | olive | olive tree | olivenbaum | olivier | olivo
papyrus: papyrus | papiro
moss: mos | moss | moos | mousse | musgo
hay: hooi | hay | heu | foin | heno | fieno
grass: gras | grass | herbe | hierba | erba
smoke: rook | rokerig | smoke | rauch | fumee | humo | fumo
salt: zout | zeezout | salt | sea salt | salz | sel | sal | sale
mineral: mineraal | minerale | mineralen | mineral | mineralisch | mineraux
ozonic: ozonisch | ozonische | ozon | ozonic | ozone | ozono
marine: zee | zeegeur | mariene | sea | sea notes | maritime | meer | marin | marino
solar notes: zonnenoten | zonnige noten | zon | solar notes | solar | sonne | solaire
caviar: kaviaar | caviar | kaviar
monoi: monoi | monoi olie | monoi oil | tiare
spicy: specerijen | specerij | spices | spicy | kruidig | kruidige | kruiden | gewurze | wurzig | epices | epice | especias | especiado | spezie | speziato
oriental: oriental | orientaal | orientaals | orientaalse | orientalisch | orientale | oosters | oosterse
woody: houtachtig | houtachtige | houtsoorten | houtakkoorden | woody | holzig | boise | boisee | amaderado | amaderada | legnoso | legnosa | hout | wood | woods
aromatic: aromatisch | aromatische | aromatic | aromatique | aromatico | aromatica
floral: bloemig | bloemige | bloemen | bloemblaadjes | floral | florale | blumig | floreale | fleuri
fruity: fruitig | fruitige | fruity | fruchtig | fruite | frutal | fruttato
sweet: zoet | zoete | sweet | suss | sucre | dulce | dolce
powdery: poederachtig | poederig | powdery | pudrig | poudre | atalcado | cipriato
fresh: fris | frisse | fresh | frisch | frais | fresco | fresca
citrus: citrus | citrusachtig | citrusvruchten | citrus vruchten | zitrus | zitrisch | agrumes | hesperide | citrico | agrumato
aquatic: aquatisch | aquatische | aqua | aquatic | aquatique | acuatico | acquatico | marien | waterig
green: groen | groene | green | grun | vert | verde
gourmand: gourmand
chypre: chypre
fougere: fougere | fougeres | fern | varen | farn
musky: muskusachtig | musky | moschusartig | musque | almizclado | muschiato
lavandin: lavandin
peppermint: pepermunt | peppermint | pfefferminze | pfefferminz | menthe poivree | menta piperita
sichuan pepper: sichuan peper | szechuan peper | sichuan pepper | szechuan pepper | sichuanpfeffer | poivre de sichuan
white pepper: witte peper | white pepper | weisser pfeffer | poivre blanc | pimienta blanca | pepe bianco
chili pepper: chilipeper | chili peper | chili | chili pepper | chilischote | piment
jasmine sambac: sambac | jasmijn sambac | sambac jasmijn | jasmine sambac | sambac jasmine | jasmin sambac
green apple: groene appel | green apple | gruner apfel | pomme verte | manzana verde | mela verde
green mandarin: groene mandarijn | green mandarin | grune mandarine | mandarine verte | mandarina verde
date: dadel | dadels | date | dates | dattel | datteln | datte | datil | dattero
driftwood: drijfhout | driftwood | treibholz | bois flotte
maple wood: esdoornhout | esdoorn | maple wood | maple | ahornholz | bois d erable
seaweed: zeewier | seaweed | algen | algae | algue | algues | alga | alghe
cypriol: cypriol | nagarmotha | nagarmotha hout | papyrus root
calone: calone
calypsone: calypsone
meringue: meringue | schuimpje | baiser
kulfi: kulfi
cade: cade | cade olie | cade oil
chinotto: chinotto
styrax: styrax | storax
plum blossom: pruimenbloesem | plum blossom | pflaumenblute | fleur de prunier
"""
NOTE_CANON = {v.strip(): canon.strip() for line in NOTE_WORDS.strip().splitlines()
              for canon, variants in [line.split(":", 1)] for v in variants.split("|") if v.strip()}
NOTE_EN = set(NOTE_CANON.values())   # the English names, given as "en" on notes the table knows


def plain(s):
    s = re.sub(r"\b[nN]\s*[°º]\s*|\b[nN][oO]\.\s*(?=\d)", "no ", str(s or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def brand_key(brand):
    p = plain(brand)
    if p in BRAND_ALIASES:
        return BRAND_ALIASES[p]
    core = " ".join(w for w in p.split() if w not in BRAND_FILLER) or p
    return BRAND_ALIASES.get(core, core)


def brand_words(key):
    """All words that belong to this house in any spelling (to remove them from product names)."""
    words = set(key.split())
    for alias, k in BRAND_ALIASES.items():
        if k == key:
            words.update(alias.split())
    return words


def name_key(name, bkey, promo=True):
    """The name as a key: no brand words, filler or promotion words (promo=False keeps those, for the keys
    names had before PROMO_TAIL, see build)."""
    drop = brand_words(bkey)
    out = []
    for w in plain(strip_promo(name) if promo else name).split():
        if w in drop or w in NAME_FILLER:
            continue
        w = "homme" if w in MALE_WORDS else "femme" if w in FEMALE_WORDS else w
        if not out or out[-1] != w:
            out.append(w)
    return " ".join(out)


def known_house(brand):
    k = brand_key(brand)
    return k in BRAND_ALIASES or k in BRAND_ALIASES.values()


def pick_brand(brands, name):
    """The perfume house from a list like Open Beauty Facts' "L'Oréal, Giorgio Armani": the first one that
    occurs in the product name, else the first known house (BRAND_ALIASES), else the first one."""
    brands = [b.strip() for b in brands if b and b.strip()]
    if not brands:
        return ""
    words = f" {plain(name)} "
    for b in brands:
        k = brand_key(b)
        spellings = {plain(b), k} | {a for a, v in BRAND_ALIASES.items() if v == k}
        if any(s and s not in BRAND_FILLER and f" {s} " in words for s in spellings):
            return b
    return next((b for b in brands if known_house(b)), brands[0])


def strip_brand(name, brand):
    """The name without the brand in front ("Hugo Boss RED" -> "RED", "Chanel - Chance Eau Tendre" ->
    "Chance Eau Tendre"), as long as a real name is left; only the brand as written is removed, so
    "Boss Woman" by Hugo Boss stays as it is."""
    bw = plain(brand).split()
    if not bw:
        return name
    tokens = [(m.end(), w) for m in re.finditer(r"\w+", name) for w in plain(m.group()).split()]
    if [w for _, w in tokens[:len(bw)]] != bw:
        return name
    rest = name[tokens[len(bw) - 1][0]:].strip(" -–—:,|/·")
    left = [w for w in plain(rest).split() if w not in NAME_FILLER | MALE_WORDS | FEMALE_WORDS | PRODUCT_WORDS]
    return rest if left else name


def note_key(note):
    """The note as one key across shops and languages: "Rum Akkoord" = "rum", "Kastanjes" = "chestnut",
    "Tuberoos (Nachthyacint)" = "tuberose", "Indiase Patchouli" = "patchouli". "" for things that aren't a note
    ("Bovenlichaam", a lone "Noot")."""
    p = NOTE_PREFIX.sub("", plain(re.sub(r"\([^)]*\)", " ", str(note or ""))))
    if re.match(r"(?:een|de|het|a|an|the|ein|eine|un|une|una)\b", p):   # a piece of a sentence: "Een intrigerende"
        return ""
    key = " ".join(unglue(w) for w in p.split() if w not in NOTE_FILLER)
    key = " ".join(w for w in key.split() if w not in NOTE_FILLER)
    if not key or key in NOTE_JUNK:
        return ""
    if key in NOTE_CANON:            # the whole name first: "violet leaf" and "orange blossom" are notes of their own
        return NOTE_CANON[key]
    core = " ".join(w for w in key.split() if w not in NOTE_DESCRIPTORS)
    if core and core != key:
        key = core
    if key in NOTE_CANON:
        return NOTE_CANON[key]
    # "Ceder Hout", "Vetiver Hout": the material's wood is the note itself.
    if key.endswith(" hout") and key[:-5] in NOTE_CANON:
        return NOTE_CANON[key[:-5]]
    return key


# Dutch glues words together: "Kastanjeakkoord", "Vetiveressence", "Muntolie", "Leernoten", "Roosfacetten".
GLUED = ("akkoorden", "akkoord", "essences", "essence", "facetten", "noten", "olie")


def unglue(word):
    """A known note with a filler word glued on, without that word ("kastanjeakkoord" → "kastanje")."""
    if word in NOTE_CANON:
        return word
    for end in GLUED:
        stem = word[:-len(end)]
        if word.endswith(end) and len(stem) >= 3 and stem in NOTE_CANON:
            return stem
    return word


# parfumwebshop.nl puts every tier on one line under "Top noten" ("Bergamot, Appel Hart noten: Salie, Geranium
# Basis noten: Vetiver"): the heart and base notes then also come in as top notes. The top list ends at the first
# label; the notes after it come in again under their own tier.
INLINE_TIER = re.compile(r"(?:^|\s)(?:top|kop|hoofd|hart|basis|base|heart|middle|head)\s?(?:noten|notes|noot|note)\s*:", re.I)


def tier_notes(notes, tier):
    """The notes a shop gave for one tier, cut off where another tier's label starts inside the list."""
    out = []
    # "Ceder- Amberhout" (parfumwebshop.nl) is two notes.
    for n in [x for n in notes or [] for x in re.split(r"(?<=\w)-\s+", str(n)) if x.strip()]:
        m = INLINE_TIER.search(str(n))
        if not m:
            out.append(n)
            continue
        before, after = str(n)[:m.start()].strip(), str(n)[m.end():].strip()
        if before:
            out.append(before)
            break
        label_tier = "top" if re.match(r"\s*(?:top|kop|hoofd|head)", m.group(0), re.I) else \
            "heart" if re.match(r"\s*(?:hart|heart|middle)", m.group(0), re.I) else "base"
        if label_tier != tier:   # "Basisnoten: ceder" as the first top note: the rest isn't this tier
            break
        if after:                # "Hartnoten: peperhout" in the heart list: just the label repeated
            out.append(after)
    return out


# A more precise note and the general one it belongs to. When one shop says "Peper" and another "Roze peper" for the
# same perfume, they mean the same note (see merge_notes). Notes ending in another note ("bitter orange",
# "white musk") count too, without being listed here.
NOTE_PARENTS = {
    "pink pepper": "pepper", "black pepper": "pepper", "glazed chestnut": "chestnut", "bourbon vanilla": "vanilla",
    "blood mandarin": "mandarin", "blood orange": "orange", "bitter orange": "orange", "white musk": "musk",
    "clary sage": "sage", "star anise": "anise", "frankincense": "incense", "ambergris": "amber",
}


def parent_of(key, keys):
    """The general note in `keys` that this note is a more precise form of, or None."""
    p = NOTE_PARENTS.get(key)
    if p in keys:
        return p
    words = key.split()
    for i in range(1, len(words)):
        tail = " ".join(words[i:])
        if tail in keys and tail in NOTE_EN:
            return tail
    return None


# Where a note usually sits, for when shops disagree evenly (one says top, another base): from its main accord.
TOP_ACCORDS = {"citrus", "fresh", "fresh spicy", "aromatic", "fruity", "green", "aquatic"}
BASE_ACCORDS = {"woody", "amber", "vanilla", "musky", "balsamic", "leather", "gourmand", "sweet", "earthy", "smoky",
                "nutty", "powdery"}


def usual_tier(key):
    import accords   # here: accords is only needed for this tie-break
    m = accords.NOTES.get(key)
    if not m:
        return "heart"
    main = max(m, key=m.get)
    return "top" if main in TOP_ACCORDS else "base" if main in BASE_ACCORDS else "heart"


# A brand's own website: its notes are the official ones. They count as confirmed at once (no second shop needed),
# but only for that brand's perfumes (armani.com confirms Armani, never another house). Besides a pyramid, a brand
# site often only names notes in its story ("the signature chestnut accord with a leathered vanilla"): the extension
# sends those as "mentioned", without a tier.
OFFICIAL_SITES = {
    "armani.com": "Armani", "armanibeauty.com": "Armani", "giorgioarmanibeauty.com": "Armani",
    "dior.fr": "Dior", "dior.com": "Dior", "chanel.fr": "Chanel", "chanel.com": "Chanel", "guerlain.fr": "Guerlain",
    "guerlain.com": "Guerlain", "bulgari.com": "Bvlgari", "prada.com": "Prada", "prada-beauty.com": "Prada",
    "rabanne.com": "Rabanne", "hugoboss.com": "Hugo Boss", "gucci.com": "Gucci", "burberry.com": "Burberry",
    "versace.com": "Versace", "givenchybeauty.com": "Givenchy", "mugler.com": "Mugler",
    "carolinaherrera.com": "Carolina Herrera", "jeanpaulgaultier.com": "Jean Paul Gaultier",
    "dolcegabbana.com": "Dolce&Gabbana", "narcisorodriguez.com": "Narciso Rodriguez", "valentino.com": "Valentino",
    "valentino-beauty.com": "Valentino", "ysl.com": "Yves Saint Laurent", "yslbeauty.com": "Yves Saint Laurent",
    "lancome.nl": "Lancôme", "lancome.de": "Lancôme", "lancome.fr": "Lancôme", "lancome.co.uk": "Lancôme",
    "zara.com": "Zara", "goldfieldandbanks.com": "Goldfield & Banks", "etatlibredorange.com": "Etat Libre d'Orange",
    "profumum.com": "Profumum Roma",
}


# Note words that are also everyday words in a brand's story ("the" = French thé, "room" = Dutch cream): not taken
# from "mentioned" (the same list as PROSE_NOISE in content.js).
PROSE_NOISE = {"the", "te", "tee", "den", "pin", "room", "drop", "peer", "rook", "sale", "sal", "sel", "vin", "zee", "zon",
               "sea", "meer", "lis", "lys", "heu", "eik", "mos", "hars", "gras", "erba", "fico", "foin", "humo", "fumo", "lima",
               "mora", "pera", "mela", "kers", "spar", "loto", "creme", "cream", "solar", "sonne", "marin", "resin"}


def is_official(shop, brand):
    """True when this shop is the brand's own website."""
    house = OFFICIAL_SITES.get(shop)
    return bool(house) and brand_key(house) == brand_key(brand)


def merge_notes(rows):
    """The notes of one perfume from its fact rows: {tier: [note, …]}. Each note once, however the shops write it:
    - a general note merges into the one more precise form of it ("Peper" + "Roze peper" = pink pepper, confirmed
      by both shops); with two precise forms (pink and black pepper) the general one stays;
    - a note goes in the tier most shops give; an even split goes to where it usually sits;
    - it is confirmed once CONFIRM_SHOPS different shops name it, in whichever tier, or at once when the brand's own
      website names it (OFFICIAL_SITES); the official tier then wins, and a note the brand only mentions in its
      text (no tier) goes where the shops put it, or else where it usually sits."""
    official = {r["shop"] for r in rows if is_official(r["shop"], r.get("brand") or "")}
    entries = [(r["shop"], tier, note_key(n), n) for r in rows for tier in ("top", "heart", "base")
               for n in tier_notes(r["notes"].get(tier, []), tier)]
    entries += [(r["shop"], None, note_key(n), n) for r in rows if r["shop"] in official
                for n in r["notes"].get("mentioned", []) if plain(n) not in PROSE_NOISE]
    entries = [x for x in entries if x[2]]
    keys = {k for _, _, k, _ in entries}
    children = defaultdict(set)
    for k in keys:
        p = parent_of(k, keys)
        if p:
            children[p].add(k)
    into = {p: next(iter(c)) for p, c in children.items() if len(c) == 1}
    shops, spellings, tiers = defaultdict(set), defaultdict(Counter), defaultdict(set)
    for shop, tier, k, name in entries:
        final = into.get(k, k)
        shops[final].add(shop)
        if tier:
            tiers[final].add((shop, tier))
        # The precise note keeps its own spelling; a shop's spelling before a word from a brand's story.
        spellings[final][name] += (1 if final == k else 0) + (1 if tier else 0)
    out = {"top": [], "heart": [], "base": []}
    for k, s in shops.items():
        own = [t for sh, t in tiers[k] if sh in official]
        votes = Counter(t for _, t in tiers[k])
        if own:                                   # the brand's own pyramid decides
            tier = own[0]
        elif not votes:                           # only mentioned by the brand: where it usually sits
            tier = usual_tier(k)
        else:
            best = max(votes.values())
            tied = [t for t in ("top", "heart", "base") if votes[t] == best]
            tier = tied[0] if len(tied) == 1 else (usual_tier(k) if usual_tier(k) in tied else
                                                   "heart" if "heart" in tied else tied[0])
        name = max(spellings[k].items(), key=lambda kv: (kv[1], -len(kv[0])))[0]
        by_brand = bool(s & official)
        x = {"name": name, "key": k, "shops": len(s), "confirmed": len(s) >= CONFIRM_SHOPS or by_brand}
        if by_brand:
            x["official"] = sorted(s & official)[0]   # the brand's site, shown on the page
        if not x["confirmed"]:
            x["from"] = sorted(s)   # which shop named it, so a page can say where an unconfirmed note comes from
        if k in NOTE_EN:
            x["en"] = k
        out[tier].append(x)
    for tier in out:
        out[tier].sort(key=lambda x: (-x["shops"], x["name"].lower()))
    return out


# Gender words that shops add behind the name ("Stronger With You Mannen", "… voor Vrouwen"); unlike
# "Pour Homme" or "for Her" they are never part of the perfume's own name, so the displayed name drops them.
SHOP_GENDER_TAIL = re.compile(r"(?:\s+(?:voor|fur|für))?\s+(?:mannen|vrouwen|heren|dames|herren|damen)\s*$", re.I)


def display_name(name, bkey=""):
    """The name as shown: without shop gender tails ("… Mannen"), promotion words ("- Summer Deal") and the
    house's words in front ("Emporio", "Giorgio", "EA" for Armani), as long as a real name is left."""
    rest = strip_promo(SHOP_GENDER_TAIL.sub("", name).strip())
    orphans = ORPHAN_PREFIX.get(bkey)
    if orphans:
        tokens = list(re.finditer(r"[^\W_]+", rest))
        n = 0
        while n < len(tokens) and plain(tokens[n].group()) in orphans:
            n += 1
        # Only a loose sub-brand word: "Emporio Armani Stronger With You" and "Armani Code" stay as they are.
        if n and n < len(tokens) and plain(tokens[n].group()) not in brand_words(bkey):
            tail = rest[tokens[n].start():].strip(" -–—:,|/·")
            real = [w for w in plain(tail).split() if w not in NAME_FILLER | MALE_WORDS | FEMALE_WORDS | PRODUCT_WORDS]
            if real:
                rest = tail
    return rest if re.search(r"\w", rest) else name


def shouting(s):
    """ALL CAPS ("STRONGER WITH YOU", "ARMANI"): only used when no shop writes it normally."""
    letters = [c for c in s if c.isalpha()]
    return len(letters) > 3 and all(c.isupper() for c in letters)


class Groups:
    """Union-find over fact rows."""

    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def init(con):
    obf.init(con)
    con.execute("""CREATE TABLE IF NOT EXISTS catalog (
        id TEXT PRIMARY KEY, brand TEXT NOT NULL, name TEXT NOT NULL, conc TEXT NOT NULL, gender TEXT,
        search TEXT NOT NULL, shops INTEGER NOT NULL, reports INTEGER NOT NULL, confirmed INTEGER NOT NULL,
        review TEXT NOT NULL, data TEXT NOT NULL, updated INTEGER NOT NULL)""")
    con.execute("CREATE INDEX IF NOT EXISTS catalog_shops ON catalog (shops DESC)")
    # Every key a perfume was ever known by, so its id stays the same when shops' spelling shifts.
    con.execute("CREATE TABLE IF NOT EXISTS catalog_keys (key TEXT PRIMARY KEY, id TEXT NOT NULL)")
    # Barcode -> perfume, for /catalog/lookup (rebuilt with the catalog).
    con.execute("CREATE TABLE IF NOT EXISTS catalog_gtins (gtin TEXT PRIMARY KEY, id TEXT NOT NULL)")


def gender_tail(nk):
    """("stronger with you homme") -> ("stronger with you", "m"): a gender word at the end of a name key is
    the gender, not part of the name (see build). A name that is only that word keeps it."""
    words = nk.split()
    if len(words) > 1 and words[-1] in ("homme", "femme"):
        return " ".join(words[:-1]), "m" if words[-1] == "homme" else "f"
    return nk, ""


def perfume_id(key):
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def counted(values_by_shop):
    """{value_key: {"name": most common spelling, "shops": n}} from (shop, key, spelling) triples."""
    shops, spellings = defaultdict(set), defaultdict(Counter)
    for shop, key, spelling in values_by_shop:
        if key:
            shops[key].add(shop)
            spellings[key][spelling] += 1
    return {k: {"name": spellings[k].most_common(1)[0][0], "key": k, "shops": len(s), "confirmed": len(s) >= CONFIRM_SHOPS}
            for k, s in shops.items()}


def brand_spellings(rows):
    """One displayed spelling per house, over the whole catalog: the most used one ("Armani" rather than
    "Armani Beauty" or "ARMANI"), written normally when any source does ("Hugo Boss", not "hugo boss")."""
    by_key = defaultdict(Counter)
    for d in rows:
        by_key[d["_bk"]][d["brand"].strip()] += 1
    out = {}
    for bk, spellings in by_key.items():
        groups = defaultdict(Counter)
        for s, n in spellings.items():
            groups[s.casefold()][s] = n
        best = max(groups.values(), key=lambda g: sum(g.values()))
        out[bk] = max(best, key=lambda s: (not shouting(s), s != s.lower(), best[s]))
    return out


def search_text(brand, name, rows):
    """What /catalog/search looks in: the shown brand and name plus every spelling a source used, so
    "giorgio armani" still finds a perfume shown under "Armani"."""
    words = []
    for s in [brand, name] + sorted({r["brand"] for r in rows}) + sorted({r["name"] for r in rows}):
        for w in plain(s).split():
            if w not in words:
                words.append(w)
    return " " + " ".join(words)[:1000] + " "


def combine(rows, ids=None, brands=None):
    """One perfume from its fact rows."""
    keys = Counter(r["_key"] for r in rows)
    key = keys.most_common(1)[0][0]
    pid = ids.pop(0) if ids else perfume_id(key)
    shops = {r["shop"] for r in rows}
    brand = Counter(r["brand"] for r in rows).most_common(1)[0][0]
    brand = (brands or {}).get(rows[0].get("_bk"), brand)
    # The shortest common spelling of the name is usually the clean one ("Stronger With You Absolutely"
    # rather than "Emporio Armani Stronger With You Absolutely"), but not one in ALL CAPS when a shop writes
    # it normally, and without the gender words shops add ("… Mannen").
    # Shops write the retail name ("Boss Bottled"); Open Beauty Facts often has the brand glued on, which
    # strip_brand removes too eagerly ("Hugo Boss Bottled" -> "Bottled"). So shop spellings win when there are any.
    named = [r for r in rows if r["shop"] != obf.SOURCE] or rows
    names = Counter(n for _, n in {(r["shop"], display_name(r["name"], r.get("_bk", ""))) for r in named})   # one vote per shop
    top = names.most_common(1)[0][1]
    # The spelling most shops use (each shop counts once); on a tie the one not in capitals, then the shortest ("Boss Bottled" from two
    # shops beats "Bottled" and "BOTTLED" from one each).
    name = min((n for n, c in names.items() if c == top), key=lambda n: (shouting(n), len(n)))
    conc = Counter(r.get("_conc", r["conc"]) for r in rows).most_common(1)[0][0]

    gender = counted((r["shop"], r["gender"], r["gender"]) for r in rows if r["gender"])
    notes = merge_notes(rows)
    families = sorted(counted((r["shop"], note_key(f), f) for r in rows for f in r["families"]).values(),
                      key=lambda x: (-x["shops"], x["name"].lower()))
    sizes = Counter()
    for r in rows:
        for ml in set(r["sizes"]):
            sizes[ml] += 1
    gtins = sorted({g for r in rows for g in r["gtins"]})
    frag = Counter(r["perfume_id"] for r in rows if r["perfume_id"])

    review = []
    if len(frag) > 1:
        review.append("several Fragrantica matches")
    if len(gender) > 1 and not any(g["confirmed"] for g in gender.values()):
        review.append("men/women differs between shops")
    # Two shops that both list notes but share none of them: one of them is probably wrong.
    by_shop = defaultdict(set)
    for r in rows:
        for tier in ("top", "heart", "base"):
            by_shop[r["shop"]].update(note_key(n) for n in tier_notes(r["notes"].get(tier, []), tier))
    listed = [s for s in by_shop.values() if s]
    if len(listed) > 1 and not set.intersection(*listed):
        review.append("shops list different notes")

    g = max(gender.values(), key=lambda x: x["shops"])["name"] if gender else None
    confirmed = sum(n["confirmed"] for t in notes.values() for n in t)
    return {
        "id": pid, "keys": sorted(keys), "brand": brand, "search": search_text(brand, name, rows), "name": name, "conc": conc, "gender": g,
        "shops": len(shops), "reports": len(rows), "confirmedNotes": confirmed, "review": review,
        "data": {
            "notes": notes, "families": families, "genderVotes": sorted(gender.values(), key=lambda x: -x["shops"]),
            "sizes": [ml for ml, _ in sorted(sizes.items())], "gtins": gtins,
            "fragrantica": [int(i) for i, _ in frag.most_common()],
            "shopList": sorted(shops), "langs": sorted({r["lang"] for r in rows if r["lang"]}),
            "firstSeen": min(r["day"] for r in rows), "lastSeen": max(r["day"] for r in rows),
        },
    }


def build(con):
    """Rebuild the catalog table from all facts. Returns the number of perfumes."""
    con.row_factory = sqlite3.Row
    rows, sources = [], []
    for r in con.execute("SELECT * FROM facts"):
        d = dict(r)
        for k in ("sizes", "gtins", "notes", "families"):
            d[k] = json.loads(d[k] or "[]")
        sources.append(d)
    # Perfumes from Open Beauty Facts (see obf.py) count as one more source, like a shop.
    sources += obf.as_facts(con)
    # Deodorants, shower gels, body mists … of a perfume line are not the perfume (shops and older extension
    # versions sometimes sent them): left out, so "Boss Bottled Deodorant" never becomes a perfume of its own.
    sources = [d for d in sources if not obf.not_perfume(d["brand"], d["name"])]
    for d in sources:
        bk = brand_key(d["brand"])
        nk = name_key(d["name"], bk)
        if not nk:
            continue
        # A gender word at the end ("Stronger With You Mannen", "Guilty Pour Homme") says who the perfume is
        # for, so it becomes the gender instead of part of the name. Men's and women's versions still stay
        # apart through the gender. A name that is only that word ("Dior Homme") keeps it.
        d["_oldname"] = nk   # the key before this rule, so ids stay the same (see below)
        d["_promoname"] = name_key(d["name"], bk, promo=False)   # and before PROMO_TAIL
        d["_rawg"] = d["gender"] if d["gender"] in ("m", "f") else ""
        nk, implied = gender_tail(nk)
        if implied and d["gender"] not in ("m", "f", "u"):
            d["gender"] = implied
        d["_name"] = f"{bk}|{nk}"
        d["_bk"] = bk
        rows.append(d)

    # A fact without a concentration joins the single concentration that perfume has; with two or more
    # (Sauvage edt and parfum) it stays on its own.
    concs = defaultdict(set)
    for d in rows:
        if d["conc"]:
            concs[d["_name"]].add(d["conc"])
    for d in rows:
        c = concs[d["_name"]]
        d["_conc"] = d["conc"] or (next(iter(c)) if len(c) == 1 else "")
        d["_base"] = f"{d['_name']}|{d['_conc']}"

    # Men's/women's versions with the same name stay apart; facts without it join the single one there is.
    genders = defaultdict(set)
    for d in rows:
        if d["gender"] in ("m", "f"):
            genders[d["_base"]].add(d["gender"])
    for d in rows:
        g = d["gender"] if d["gender"] in ("m", "f") else (next(iter(genders[d["_base"]])) if len(genders[d["_base"]]) == 1 else "")
        d["_key"] = d["_base"] + "|" + g
        # Keys this row may have had before: the name with the gender word, and the gender as the shop
        # sent it (before it was filled in from the name or from the only men's/women's version).
        d["_oldkeys"] = [f"{d['_bk']}|{n}|{d['_conc']}|{x}" for n in dict.fromkeys((d["_name"].split("|", 1)[1], d["_oldname"], d["_promoname"]))
                         for x in dict.fromkeys((g, d["_rawg"], ""))]

    groups = Groups(len(rows))
    first_by = {}
    for i, d in enumerate(rows):
        for link in [("k", d["_key"])] + [("g", g) for g in d["gtins"]]:
            if link in first_by:
                groups.join(first_by[link], i)
            else:
                first_by[link] = i
    clusters = defaultdict(list)
    for i, d in enumerate(rows):
        clusters[groups.find(i)].append(d)

    # Stable ids: a perfume keeps the id one of its keys had before. When an old perfume is split, the part
    # with most reports keeps the id and the others get a new one; when two merge, the id most of its rows had wins.
    brands = brand_spellings(rows)
    known = dict(con.execute("SELECT key, id FROM catalog_keys").fetchall())
    taken, out = set(), []
    for c in sorted(clusters.values(), key=len, reverse=True):
        old = Counter(next(known[k] for k in r["_oldkeys"] if k in known) for r in c
                      if any(k in known for k in r["_oldkeys"]))
        ids = [i for i, _ in old.most_common() if i not in taken]
        p = combine(c, ids[:1], brands)
        while p["id"] in taken:   # a new id that happens to be in use already
            p["id"] = perfume_id(p["id"] + "+")
        taken.add(p["id"])
        out.append(p)
    now = int(time.time())
    with con:
        con.executemany("INSERT OR REPLACE INTO catalog_keys (key, id) VALUES (?, ?)",
                        [(k, p["id"]) for p in out for k in p["keys"]])
        con.execute("DELETE FROM catalog")
        con.execute("DELETE FROM catalog_gtins")
        con.executemany("INSERT OR IGNORE INTO catalog_gtins (gtin, id) VALUES (?, ?)",
                        [(g, p["id"]) for p in out for g in p["data"]["gtins"]])
        con.executemany("""INSERT OR REPLACE INTO catalog (id, brand, name, conc, gender, search, shops, reports,
                confirmed, review, data, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        [(p["id"], p["brand"], p["name"], p["conc"], p["gender"],
                          p["search"], p["shops"], p["reports"],
                          p["confirmedNotes"], json.dumps(p["review"]), json.dumps(p["data"], ensure_ascii=False), now)
                         for p in out])
    return len(out)


def row_out(r, full=False):
    p = {"id": r["id"], "brand": r["brand"], "name": r["name"], "conc": r["conc"] or None, "gender": r["gender"],
         "shops": r["shops"], "confirmedNotes": r["confirmed"]}
    if full:
        data = json.loads(r["data"])
        p.update({"reports": r["reports"], "review": json.loads(r["review"]), **data, "license": "ODbL-1.0"})
        if obf.SOURCE in data.get("shopList", []):
            p["attribution"] = obf.ATTRIBUTION
    return p


def search(con, q):
    words = plain(q).split()[:6]
    if not words:
        return []
    con.row_factory = sqlite3.Row
    where = " AND ".join("search LIKE ?" for _ in words)
    rows = con.execute(f"SELECT * FROM catalog WHERE {where} ORDER BY shops DESC, reports DESC LIMIT 20",
                       [f"% {w}%" for w in words])
    return [row_out(r) for r in rows]


def perfume(con, pid):
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM catalog WHERE id=?", (pid,)).fetchone()
    return row_out(r, full=True) if r else None


GTIN_RE = re.compile(r"^\d{8,14}$")


def lookup(con, gtins=(), brand="", name="", conc="", gender=""):
    """The perfume a shop page shows, for the extension's "own database first" (GET /catalog/lookup):
    first by barcode, then by brand + name + concentration (+ men/women) the same way build() matches.
    Only exact matches; no guessing. Returns the full perfume or None."""
    con.row_factory = sqlite3.Row
    for g in gtins:
        g = str(g).strip()
        if GTIN_RE.match(g):
            r = con.execute("SELECT id FROM catalog_gtins WHERE gtin=?", (g.zfill(13)[-13:] if len(g) <= 13 else g,)).fetchone()
            if r and (p := perfume(con, r["id"])):
                return p
    bk = brand_key(brand)
    nk, implied = gender_tail(name_key(name, bk))
    if not bk or not nk:
        return None
    g = gender if gender in ("m", "f") else implied
    # Every key this brand + name was ever known by (keys are "brand|name|conc|gender"; plain() keeps them free
    # of LIKE wildcards). A concentration or gender the page gives must fit; what it doesn't give may be anything,
    # but then it has to point at one perfume only (Guilty for men and for women: no match).
    known = [(k.split("|")[2], k.split("|")[3], i) for k, i in
             con.execute("SELECT key, id FROM catalog_keys WHERE key LIKE ?", (f"{bk}|{nk}|%",)) if k.count("|") == 3]
    known = [(c, kg, i) for c, kg, i in known if (not conc or c in (conc, "")) and (not g or kg in (g, ""))]
    for subset in ([x for x in known if x[0] == conc and x[1] == g], [x for x in known if x[0] == conc or x[1] == g], known):
        ids = {i for _, _, i in subset if con.execute("SELECT 1 FROM catalog WHERE id=?", (i,)).fetchone()}
        if len(ids) == 1:
            return perfume(con, ids.pop())
        if len(ids) > 1:
            return None
    return None


def stats(con):
    one = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "perfumes": one("SELECT COUNT(*) FROM catalog"),
        "withConfirmedNotes": one("SELECT COUNT(*) FROM catalog WHERE confirmed > 0"),
        "fromSeveralShops": one(f"SELECT COUNT(*) FROM catalog WHERE shops >= {CONFIRM_SHOPS}"),
        "toReview": one("SELECT COUNT(*) FROM catalog WHERE review != '[]'"),
        "brands": one("SELECT COUNT(DISTINCT brand) FROM catalog"),
        "updated": one("SELECT MAX(updated) FROM catalog"),
        "fromOpenBeautyFacts": one(f"SELECT COUNT(*) FROM catalog WHERE data LIKE '%\"{obf.SOURCE}\"%'"),
        "license": "ODbL-1.0",
        "attribution": obf.ATTRIBUTION,
    }

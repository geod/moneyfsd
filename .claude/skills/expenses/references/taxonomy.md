# Taxonomy

The default category structure and the keyword tables that drive auto-tagging. Designed to be **comprehensive enough to cover most US household spending** without being so granular that it becomes useless.

## Default categories

```
Housing
  Mortgage / Rent
  Property Tax
  HOA
  Utilities (Electric, Gas, Water, Trash, Internet, Phone)
  Home Improvement
  Home Services       (cleaners, gardener, pool, handyman)
  Insurance (homeowners, renters)

Food & Dining
  Groceries
  Restaurants
  Coffee
  Food Delivery       (DoorDash, Uber Eats)
  Misc                (vending, snacks, ambiguous)

Travel
  Airlines
  Hotels
  Lodging / Booking   (Airbnb, VRBO)
  Car Rental
  Transit (Travel)    (rail, metro abroad)
  Ski                 (lift tickets, rentals, ski school)
  Card Travel Credit  (negative — offsets travel)

Auto & Transport
  Fuel
  Tolls
  Auto Service        (oil change, repair, tires)
  Ride Share          (Uber, Lyft, Waymo)
  Parking
  Transportation      (subway, bus, local transit at home)
  DMV / Registration

Kids
  School (tuition, fees)
  Camps
  Activities
  Toys
  Misc

Health
  Medical
  Dental
  Vision
  Pharmacy
  Mental Health
  Health Insurance

Personal Care & Fitness
  Gym
  Yoga / Pilates / Studio
  Salon / Barber
  Skincare / Cosmetics
  Massage / Spa

Shopping & Retail
  Amazon
  Big Box             (Costco, Target, Walmart)
  Clothing
  Home Goods          (Williams Sonoma, Ikea, Pottery Barn)
  Electronics
  Books
  Online Merchant     (PayPal/Venmo to merchants, Etsy)
  Other Retail

Subscriptions & Software
  Streaming / Media
  News / Publications / Books
  Software / Tools

Entertainment
  Movies / Theater
  Concerts / Live
  Museums
  Games / Arcade

Pets
  Vet
  Food / Supplies
  Grooming / Boarding

Home Services
  Cleaning / Housekeeping
  Landscaping
  Plumbing / Electrical
  Pest Control
  Dry Cleaning / Laundry

Professional Services
  Legal
  Accounting / Tax Prep
  Notary / Mailing
  Medical Memberships  (NEJM, AMA, etc.)

Insurance
  Auto
  Life
  Umbrella
  Other (non-home, non-health)

Charity & Gifts
  Charity / Non-profit
  Gifts (to people)

Fees
  Bank Fees
  Credit Card Annual Fee
  Late Fees / Interest
  Statement Credit    (negative — card reward)

Cash
  ATM                 (opaque — flag for user review)

Misc
  Unknown             (matches nothing — Phase 4 will surface these)
```

## Keyword matching strategy

Process rows in order; **first match wins**. Order matters because a row like "Costco Gas" should match Fuel before Big Box.

For each row, lowercase the description and check against keyword groups in this order:

### 1. User-confirmed one-off overrides

These are the highest-priority rules — the user has already told you about a specific exception. Match on (Date, description-substring, Amount).

```python
if row['Date']=='12/04/2025' and 'rei' in d and round(row['Amount'],2)==415.94:
    return ('Charity & Gifts', 'Gifts')
```

Add new overrides to `consolidate.py` whenever the user confirms one in Phase 4.

### 2. Trust the source bank's category (cards only)

Apple Card and Mint-style exports have decent categorization. Map the bank's category to your taxonomy:

```python
apple_map = {
    'Restaurants':         ('Food & Dining', 'Restaurants'),
    'Grocery':             ('Food & Dining', 'Groceries'),
    'Gas':                 ('Auto & Transport', 'Fuel'),
    'Airlines':            ('Travel', 'Airlines'),
    'Hotels':              ('Travel', 'Hotels'),
    'Car-rentals':         ('Travel', 'Car Rental'),
    'Tolls':               ('Auto & Transport', 'Tolls'),
    'Transportation':      ('Auto & Transport', 'Transportation'),
    'Govt-services-parking': ('Auto & Transport', 'Parking / Govt'),
    'Medical':             ('Health', 'Medical'),
    'Utilities':           ('Utilities', 'Utilities'),
    'Insurance':           ('Insurance', 'Insurance'),
}
# Don't map Apple's 'Entertainment' or 'Shopping' — too coarse, fall through
```

### 3. Merchant keyword tables

The bulk of the work. See `assets/default_taxonomy.yaml` for the full table; here's a representative slice:

```yaml
Kids:
  Kids:
    - kumon
    - scholarshare
    - "kid "
    - child
    - toddler
    - baby
    - diaper
    - gymnastics
    - legoland
    - pokemon
    - american girl
    - build-a-bear
    - lego
    - "summer camp"
    - pediatric
    - boy scout
    - girl scout
    - school tuition

Travel:
  Ski:
    - snow.com
    - vail resorts
    - mammoth mtn
    - black tie ski
    - ikon pass
    - epic pass
    - "phil's ski"
    - ski school
    - ski rental
    - snowboard
  Lodging / Booking:
    - airbnb
    - vrbo
    - kayak
    - expedia
    - booking.com
    - hopper
  Airlines:
    - air france
    - lufthansa
    - delta
    - united
    - american air
    - alaska air
    - southwest
    - jetblue
    - british air
  Hotels:
    - marriott
    - hilton
    - hyatt
    - sheraton
    - westin
    - "ritz "
    - four seasons
    - wyndham
    - ihg
    - "hotel "
    - hotels.com
  Car Rental:
    - hertz
    - avis
    - enterprise
    - budget rent
    - national car
    - sixt
    - alamo

Food & Dining:
  Coffee:
    - starbucks
    - peets
    - philz
    - blue bottle
    - dutch bros
    - coffee
    - cafe
  Groceries:
    - whole foods
    - trader joe
    - safeway
    - ralphs
    - albertsons
    - sprouts
    - costco whs
    - costco whse
    - aldi
    - vons
    - pavilions
    - grocery
  Food Delivery:
    - doordash
    - uber eats
    - grubhub
    - postmates
    - caviar
    - instacart
  Restaurants:
    - restaurant
    - bistro
    - grill
    - kitchen
    - bbq
    - sushi
    - pizza
    - taco
    - burger
    - "bar "
    - tavern
    - "pub "
    - brewery
    - eatery
    - dining

Auto & Transport:
  Ride Share:
    - uber
    - lyft
    - waymo
    - curb
    - taxi
    - zipcar
  Fuel:
    - chevron
    - shell
    - exxon
    - mobil
    - "76 "
    - arco
    - "bp "
    - circle k
    - costco gas
    - sunoco
    - valero
    - texaco

Subscriptions & Software:
  Streaming / Media:
    - netflix
    - hulu
    - spotify
    - apple.com/bill
    - itunes
    - prime video
    - youtube premium
    - disney+
    - hbo
    - "max "
    - paramount+
    - peacock
  News / Publications / Books:
    - nytimes
    - new york times
    - wsj
    - wall street journal
    - washington post
    - economist
    - financial times
    - atlantic
    - new yorker
    - substack
    - kindle
    - audible
  Software / Tools:
    - chatgpt
    - openai
    - anthropic
    - github
    - dropbox
    - google
    - icloud
    - microsoft
    - office 365
    - adobe
    - figma
    - notion
    - 1password

Health:
  Medical:
    - cvs
    - walgreens
    - rite aid
    - pharmacy
    - kaiser
    - sutter
    - hospital
    - clinic
    - dentist
    - dental
    - orthodontist
    - vision
    - medical
    - urgent care
    - blue shield
    - blue cross
    - anthem
    - cigna
    - one medical

Shopping & Retail:
  Amazon:
    - amazon
    - amzn mktp
    - amzn.com
  Big Box:
    - target
    - walmart
    - wal-mart
    - costco
    - "sam's club"
    - "bj's whole"
  Clothing:
    - nordstrom
    - macy
    - zara
    - uniqlo
    - "gap "
    - old navy
    - banana republic
    - j.crew
    - jcrew
    - nike
    - adidas
    - lululemon
    - athleta
    - madewell
    - everlane

Personal Care & Fitness:
  Fitness:
    - lifetime fitness
    - life time
    - equinox
    - crunch
    - "24 hour fitness"
    - planet fitness
    - ymca
    - yoga
    - pilates
    - barre
    - orangetheory
    - classpass
    - peloton
  Personal Care:
    - massage
    - spa
    - nail
    - salon
    - barber
    - haircut
    - sephora
    - ulta

Home Services:
  Home Services:
    - plumber
    - plumbing
    - electrician
    - hvac
    - roofing
    - landscap
    - gardener
    - cleaning
    - housekeep
    - "maid "
    - pest control
    - exterminator
    - pool service
    - handyman
    - termite
    - dry cleaner
    - cleaners
    - laundry

Insurance:
  Insurance:
    - geico
    - state farm
    - progressive
    - allstate
    - "aaa "
    - mercury insurance
    - farmers insurance
    - usaa

Charity & Gifts:
  Charity:
    - donation
    - charity
    - non-profit
    - nonprofit
    - fundrais
    - gofundme
    - givelively
    - redcross
    - united way

Pets:
  Pets:
    - petco
    - petsmart
    - chewy
    - veterin
    - "dog "
    - "cat "
    - "pet "
```

### 4. Fallback: Misc / Unknown

If nothing matched, route to `(Misc, Unknown)`. These rows are surfaced to the user in Phase 4 for review. **Don't make up a category** — Misc is honest and prompts the user to correct.

## Order-of-operations gotchas

- **"costco gas" → Fuel, not Big Box.** Check Fuel keywords before Big Box.
- **"costco whs" / "costco whse" → Big Box, not Fuel.** Use the specific phrasing.
- **"market" matches everything.** Be careful — "stock market" or "Sushi Market" will hit. Anchor with surrounding context where possible (`whole foods market` not bare `market`).
- **Ski vs. Sports & Hobbies.** Ski lift tickets and ski rentals are *Travel*, not Sports. People budget for ski trips; they don't budget for "sports" as a recurring expense in the same way.
- **REI ambiguity.** REI is a Sports & Hobbies retailer for most users, but ski boots from REI on the way to a ski trip are Travel/Ski. Use a Date+Description override if the user calls it out.
- **Joint vs. attribution mistakes.** A joint Costco run on the joint card stays under "Joint" Source — don't try to attribute to one person unless the cardholder column says so.

## Persisting new rules

Whenever the user corrects a categorization:

1. Identify the **rule** that should fire next time. Is it a new keyword? A specific (Date, merchant, amount) override? A new subcategory?
2. Add it to the right keyword table or override list in `scripts/consolidate.py`.
3. Save the updated `Lifestyle Expenses.csv`.
4. **Tell the user** what you did: "Added 'after-school program' to the Kids keyword table — future imports will catch this without me asking."

Without persistence, the user redoes the same fixes every refresh and stops trusting the workflow.

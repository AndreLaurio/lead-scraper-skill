# OpenStreetMap tags for business discovery

`find_businesses.py --what <name>` maps ~70 friendly names to OSM tags; run
`--list-categories` to see them. For anything else pass raw tags with
`--tag key=value` (repeatable, OR-ed together).

## The five keys that hold almost every business

| Key | Covers | Examples |
|---|---|---|
| `amenity` | services the public walks into | `dentist`, `restaurant`, `cafe`, `bank`, `pharmacy`, `veterinary`, `car_wash`, `driving_school` |
| `shop` | retail of any kind | `bakery`, `hairdresser`, `car_repair`, `bicycle`, `pet`, `optician`, `florist` |
| `office` | companies with a desk, not a storefront | `lawyer`, `accountant`, `insurance`, `estate_agent`, `it`, `advertising_agency`, `architect`, `company` |
| `craft` | trades and makers | `plumber`, `electrician`, `roofer`, `carpenter`, `photographer`, `brewery` |
| `healthcare` | medical, often doubled with amenity | `dentist`, `doctor`, `clinic`, `physiotherapist`, `psychotherapist` |

Also useful: `leisure=fitness_centre`, `tourism=hotel`, `industrial=factory`.

Look up any value at `https://wiki.openstreetmap.org/wiki/Tag:<key>=<value>`, or
search taginfo (`https://taginfo.openstreetmap.org/search?q=<word>`) to see how
mappers actually tag something and how many instances exist.

## Tips

- Many businesses carry only a generic tag (`office=company`, `shop=yes`). Querying
  `--tag office=company` in a city gives a broad list you can filter by name/website.
- `--with-website-only` trims to businesses the enricher can actually work on; drop it
  when phone-only leads are acceptable (OSM phones are usually accurate).
- `--exact-boundary` restricts to the administrative polygon; default is the bounding
  box, which is faster and includes suburbs.
- `--radius-km 25` with a town name is the right tool for rural areas.
- Coverage is uneven. Expect dense data in Germany, UK, Netherlands, France, Spain;
  moderate in big US/Canadian/Australian cities; sparse elsewhere. When thin, switch
  to web discovery (see `search-recipes.md`).
- OSM data is ODbL: credit "© OpenStreetMap contributors" if the list is published.

# Providers

Find+ polls one or more location providers on a schedule and stores every
distinct sighting under a common schema, regardless of source.

## Google Find Hub

Uses the vendored GoogleFindMyTools client. `findplus auth` opens Chrome for
an interactive Google sign-in (undetected-chromedriver, so Google sees a
normal browser sign-in, not an API client). Find+ then stores a long-lived
Android token and the end-to-end-encryption owner key needed to decrypt tag
locations, and polls on your configured interval.

> This history consists of locations reported through Google's Find Hub
> network. Moto Tag uses nearby participating Android devices to report its
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

## Apple Find My

Optional extra: `pip install 'findplus[apple]'`. Uses the `findmy` library.
Register an accessory with `findplus apple add-accessory`, supplying either
a pairing `.plist` export or a raw private key. Genuine Apple AirTags
require extracting their pairing keys from an Apple device that has already
paired with them; most users cannot do this, so Apple support in practice
covers accessories you control the key material for.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable. Find+ can only query accessories whose keys you
hold; genuine AirTags require extracting pairing keys, which most users
cannot do.

### Accuracy values

Apple reports a confidence label rather than a radius in metres. Find+ maps
each label to a fixed figure so the accuracy column has something to show:
excellent 10 m, good 30 m, medium 65 m, poor 150 m. An unrecognised or
missing label is treated as poor. These figures are estimates chosen for
display. They are not measured, and Apple publishes no metre equivalent.

## Checking provider status

```
$ findplus providers
```

Lists every installed provider and whether it is authenticated and ready to
poll (`findplus providers --json` for machine-readable output).

---
[[Home]]

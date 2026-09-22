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

Apple reports a confidence label (excellent, good, medium or poor) rather
than a radius in metres, and Apple publishes no metre equivalent for that
label. Find+ does not invent one: an Apple observation's accuracy is always
stored as unknown (`null`), never a guessed figure. The dashboard shows
"Accuracy unknown" for these fixes instead of the `±N m` reading Google
observations carry, and exports leave the accuracy column empty. The
confidence label itself is still kept alongside the observation for anyone
who wants it, just never converted into a number.

Geofence enter/exit decisions still need *some* radius to reason about
sparse or missing accuracy — that fallback (`geofence_default_accuracy_meters`
in Settings) is a documented, conservative constant used only to decide
which side of a place boundary a fix is on. It never becomes the observation's
stored or displayed accuracy.

## Checking provider status

```
$ findplus providers
```

Lists every installed provider and whether it is authenticated and ready to
poll (`findplus providers --json` for machine-readable output).

---
[[Home]]

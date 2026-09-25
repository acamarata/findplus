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
> network. Your trackers use nearby participating Android devices to report their
> location. Location updates can therefore be delayed, sparse, or
> unavailable, and this application should not be treated as real-time
> emergency or child-safety GPS tracking.

## Apple Find My

Optional extra: `pip install 'findplus[apple]'`. Uses the `findmy` library
(FindMy.py 0.10). Register an accessory with `findplus apple add-accessory`,
supplying one of:

- the decrypted pairing record the Find My app keeps for an accessory (a
  plist with `privateKey`, `sharedSecret` and `pairingDate`). FindMy.py parses
  it and Find+ follows the accessory's rolling keys;
- a flat plist with a `Private Key` field, or a raw base64 private key, for a
  tag that broadcasts one fixed key. Find My keys are P-224, so the key must
  be 28 bytes; any other length is refused when you add it.

Genuine Apple AirTags require extracting their pairing keys from an Apple
device that has already paired with them; most users cannot do this, so Apple
support in practice covers accessories you control the key material for.
Locating any accessory also needs an Apple ID sign-in (see
[Sign in](Sign-in)): Apple only answers location queries from a signed-in
account.

Apple Find My locations come from nearby Apple devices and can be delayed,
sparse or unavailable. Find+ can only query accessories whose keys you
hold; genuine AirTags require extracting pairing keys, which most users
cannot do.

### Accuracy values

Each Apple report carries a confidence value (1 to 3) and a one-byte
horizontal accuracy field whose unit neither Apple nor FindMy.py documents.
Neither is a radius Find+ can stand behind, so Find+ does not invent one: an
Apple observation's accuracy is always stored as unknown (`null`), never a
guessed figure. The dashboard shows "Accuracy unknown" for these fixes instead
of the `±N m` reading Google observations carry, and exports leave the
accuracy column empty. Both raw values are kept in the observation's metadata
for anyone who wants them, just never converted into a number.

Each poll asks Apple for the newest report from the last seven days. No
report in that window means no new observation; Find+ never fills the gap.

Geofence enter/exit decisions still need *some* radius to reason about
sparse or missing accuracy. That fallback (`geofence_default_accuracy_meters`
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

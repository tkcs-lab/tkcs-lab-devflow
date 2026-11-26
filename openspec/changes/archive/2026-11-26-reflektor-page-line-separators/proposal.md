## Why

The Reflektor change report page was refused whenever a changed file held a line or paragraph separator (U+2028, U+2029), U+0085 or a vertical tab, form feed or information-separator control character, because the page embeds every changed file's content. Any change to such a file lost its page on the board card, although nothing in it was unsafe.

## What Changes

- A page whose data holds up to 1000 of these characters is no longer refused for them.
- A window around each of them, in the raw data and in every data string, is scanned for credentials a second time with the character read as a space and deleted, the way the report viewer shows it on one line, so a credential split around the character is still found and the page is refused with the credential reason.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `role-dispatch`: a requirement for line separators in the page data is added.

## Impact

The Reflektor page check of `tld roles reflektor-html`, its tests, the reflektor guide and the changelog. The secret-scan hook and the board's page rule are unchanged.

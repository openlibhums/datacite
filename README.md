# datecite
Allows staff to mint Datacite DOIs.

## Installation
- Clone into the `/path/to/janeway/src/plugins` folder
- Checkout the required version
- Run `install_plugins` from the src folder
- Accessible from /manager/plugins/ page

## Note on test deposits

While a site runs in debug mode, the plugin deposits to DataCite's test API rather than the live one. DOIs minted against the test system do not resolve and are periodically cleared by DataCite.

# Demand fixtures

Wire shapes for the demand-import datasets (plan 122 phase 3). The BLS v2
payload follows the documented `REQUEST_SUCCEEDED` shape (the public endpoint
answered 503 'website busy' at capture time, so this is the documented
response, not a live snapshot); the Adzuna history payload follows the
documented `{month: {"YYYY-MM": count}}` shape. Tests never hit the network.

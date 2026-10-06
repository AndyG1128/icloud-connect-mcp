# License and distribution scope

## Published source beta

The published beta is the reviewed **authored-source Git repository** at
https://github.com/AndyG1128/icloud-connect-mcp . This document describes the scoped
source distribution, not a public binary or shared hosted service.
LICENSE and the explicit authored-code grant in NOTICE.md are licensed as
**AGPL-3.0-or-later**, under the owner's conditional approval evaluated for this
source-distribution scope. Dependency license expressions and notices remain
unchanged, including every “only” versus “or later” distinction. No OpenSSL
linking exception is added and no dependency is relicensed.

This is a reasoned scope assessment from the exact artifact contents and license
texts, not an automated scan certifying legal clearance of an installed service.
The authors' preferred source, configuration/build/install scripts and synthetic
tests are present. AGPL section 1 expressly distinguishes Corresponding Source
of a source-form work from the source required for object-code/installed works;
sections 4/5 govern source conveyance. No restrictive resource or native dependency
binary is conveyed by this published source set. That supports the narrow authored
source grant; it does not certify a combined installed binary or a hosted service.

Source-form tarballs made from the same set have the same source-license basis.
The project wheel also contains authored .py source/metadata/notices, no dependency
native libraries; it is not blocked merely because lxml/qh3 exist upstream. It is
nonetheless deferred as a public package: publish matching preferred build source
and source-access directions alongside any future package and reassess the actual
contents. A file extension does not determine source/object status. Do not assert
that the native dependency collection is part of the cleared source release.

## Declared runtime grants

The pinned Python interfaces used by the connector have compatible declared
source grants: CalDAV 3.3.1 permits GPL-3.0-or-later OR Apache-2.0 (Apache-2.0
selected), icalendar-searcher 1.0.6 is AGPL-3.0-or-later, recurring-ical-events
3.8.2 and x-wr-timezone 2.0.1 are LGPL-3.0-or-later. certifi is MPL-2.0.
All 55 runtime/test/build distributions' exact expressions, upstream archives,
checksums and notices are recorded in dependencies.json and notices/manifest.json.
“Unmodified” means no release-preparation changes; it does not establish that
upstream native wheels contain no vendor patches. The notice collection is
license/SBOM information, not the actual libraries, stylesheet assets or binaries.

## Evidence by file and artifact

release-scope-map.json is the exact file/package/version/presence matrix. Its
principal conclusions are:

- lxml 6.1.3 `src/lxml/isoschematron/resources/xsl/RNG2Schtrn.xsl` and
  `XSD2Schtrn.xsl`: pinned LICENSES.txt calls them unlicensed; actual files have
  authorship comments without an established grant. They occur in lxml's upstream
  sdist/wheel and the private dependency-source bundle. They are absent from the
  project's Git source, own wheel and own tarball. The connector/CalDAV use etree;
  inspected sources do not import Schematron or use either stylesheet. Permission
  to redistribute the whole upstream archive must not be inferred from lxml BSD.
- qh3 2.0.4: its source manifests select non-FIPS aws-lc-sys 0.45.0 through rustls
  0.23.45/aws-lc-rs 1.18.1. The exact non-FIPS LICENSE explicitly relicenses
  OpenSSL-derived code under Apache-2.0 and retains ISC/MIT/BSD component terms.
  Optional aws-lc-fips-sys 0.14.2 is in Cargo.lock/SBOM and the private source
  collection, with `ISC AND (Apache-2.0 OR ISC) AND OpenSSL`. It is not requested
  by the inspected default source feature graph. Its actual inclusion in the
  upstream native `_hazmat.abi3.so` is not established by a lock/SBOM alone. No
  dependency native extension ships in our source/wheel/tarball; the old-OpenSSL
  combined-binary compatibility question remains for a native runtime bundle/image.
- lxml's exact fresh wheel exposes libiconv 1.18, libxml2 2.14.6, libxslt 1.1.43
  and zlib 1.3.2. libiconv's exact library/header grant is LGPL-2.1-or-later;
  its CLI/build files retain their own grants. Source archives/notices were
  retrieved. Static LGPL binary redistribution still needs applicable source,
  changes/build and relink materials; a generic license text does not suffice.
- cryptography 50.0.2 exposes OpenSSL 4.0.3 (Apache-2.0); PyYAML 6.0.3 exposes
  libyaml 0.2.5 (MIT). Their upstream sources/notices were retrieved. cffi 2.1.1
  bundled libffi's exact version remains unknown. Compiler/options/patches and
  complete native source/build materials have not been reconstructed.
- The 87-package Debian test-base inventory is test evidence only. No connector
  image exists. A future OCI image additionally conveys Python, OS and native
  binaries and requires its own complete license/source/relink review.

These facts clear the listed *redistribution* blockers from the narrow project
source set because those files are absent. They do not erase the obligations of
another artifact or classify all installed dependencies as System Libraries.
There is no requirement here to rebuild every upstream binary to the identical
hash; missing provenance is missing source/build/permission evidence, not failure
to demonstrate bit-for-bit reproduction of someone else's build.

## Separate installed-service/network obligations

Separate dependency installation is **not** an AGPL exemption. Python imports and
intimate shared-address-space calls can form a covered combination. AGPL section
1 includes required non-system library sources for executable combinations; the
FSF section-13 FAQ explicitly includes libraries under other licenses unless
System Libraries. No blanket System Library exception is assumed here.

This publication does not operate a shared server or offer a finished combined
network-source package. Operators offering a modified/covered combined service
remotely must prominently offer no-cost access to the exact running version's
Corresponding Source, with required library sources/build/install materials and
preserved original terms. See source-access.md for the materials and checks.
An unchanged source repository plus a requirements lock is not automatically a
complete source offer for the operator's runtime. The private 381-archive bundle
is not to be uploaded as a shortcut: it includes unused/uncleared resources.

For an installed combination, classification of the unused Schematron assets and
exact native feature/source closure still needs qualified legal review or adequate
upstream clarification before claiming the source offer/combined distribution is
complete. If covered runtime content includes old-OpenSSL FIPS code, establish
compatible permission or an appropriate upstream-confirmed build; no exception
can be assumed from our authored grant. There is no new runtime gate or functionality
change here; these are distribution/hosting compliance distinctions.

## Publication formats

| Format | Disposition | Remaining requirement |
|---|---|---|
| Authored source Git repository | Published source-only beta | Preserve license/notices and source-access instructions; no private history or runtime data included |
| Project source tarball | Same scoped source basis; deferred optional artifact | Produce from approved tree, checksum it and provide the same notices/build files; no bundled dependencies |
| Project wheel without dependencies | No embedded lxml/native redistribution blocker; deferred | Match approved source/build materials; inspect final members and keep equivalent source access; no combined-runtime clearance claim |
| Dependency-source bundle | Blocked; remains private | Clarify lxml resource grants or qualified scope assessment; component terms/source-build closure; classify optional FIPS/source aggregation correctly |
| Container/native wheelhouse | Blocked; no image released | Exact contents/native feature inventory, component notices, source access and applicable LGPL relink/base-image compliance |

Primary basis: [AGPL sections 1, 4–6 and 13](https://www.gnu.org/licenses/agpl.en.html),
[FSF network Corresponding Source FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#AGPLv3CorrespondingSource),
[FSF combined versus aggregate FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#MereAggregation),
and the exact pinned upstream grant files referenced in the inventories.

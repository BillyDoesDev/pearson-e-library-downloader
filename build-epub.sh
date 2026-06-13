#!/bin/bash

if [[ $# -lt 1 ]]; then
    echo "Usage: build-epub.h path/to/OPS/dir (Note: it's usually download-dir/OPS)"
    exit 1
fi

# Build EPUB directory
mkdir -p epub-build/META-INF
mkdir -p epub-build/OPS

# Copy all OPS content
cp -r $1/* epub-build/OPS/

# Create mimetype (must be first, uncompressed)
echo -n "application/epub+zip" > epub-build/mimetype

# Create container.xml
cat > epub-build/META-INF/container.xml << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
EOF

# We also need toc.ncx - create a minimal one since the opf references it
cat > epub-build/OPS/toc.ncx << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="9789361596018"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>Computer Science and Information Technology</text></docTitle>
  <navMap>
    <navPoint id="navPoint-1" playOrder="1">
      <navLabel><text>Start</text></navLabel>
      <content src="Pg001.xhtml"/>
    </navPoint>
  </navMap>
</ncx>
EOF

echo "Structure ready. Building EPUB..."

# Build the zip (mimetype first, uncompressed; everything else compressed)
cd epub-build

book_trail="$(date +%s)"
zip -X0 ../book-$book_trail.epub mimetype
zip -r9 ../book-$book_trail.epub META-INF OPS

echo "Done!"
ls -lh ../book-$book_trail.epub

cd ..
rm -rf epub-build
echo "Removed build dir"

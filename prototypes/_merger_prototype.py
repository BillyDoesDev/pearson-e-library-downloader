from pathlib import Path

book_path = Path("pearson-CSIT")
# pages = [book_path.glob("Toc*.xhtml")] + sorted(book_path.glob("Pg*.xhtml"))[:-1]
pages = (
    list(book_path.rglob("Toc*.xhtml"))
    + sorted(book_path.rglob("Pg*.xhtml"))[:-1]
)

render_dir = Path("render")
render_dir.mkdir(parents=True, exist_ok=True)

splits = 5
chunk_size = len(pages) // splits
residue = len(pages) % splits

page_index = 0
for i in range(splits+residue):
    print(f"Writing split {i+1}...")
    with Path(render_dir / f"merged-split-{str(i).rjust(3, '0')}.html").open("w") as f:
        f.write("<html><body>")

        _start = page_index
        while page_index < min(_start+chunk_size, len(pages)):
            page = pages[page_index]
            f.write(
                f'''
                <iframe
                    src="{page.name}"
                    style="
                        width:878px;
                        height:1115px;
                        border:none;
                        display:block;
                        page-break-after:always;
                    ">
                </iframe>
                '''
            )
            page_index += 1

        f.write("</body></html>")

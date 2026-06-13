from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
import urllib

from requests.adapters import HTTPAdapter

logging.basicConfig(
    format="[{levelname}] {message}",
    style="{",
    level=logging.INFO,
)

cookie_data = {}
with open(".cookies.json") as f:
    cookie_data = json.load(f)
    _ = cookie_data["Request Cookies"]["user-info"]
    user_info = json.loads(_)

cookie_string = "; ".join(
    [f"{k}={urllib.parse.quote(v)}" for k, v in cookie_data["Request Cookies"].items()]
)

user_id = user_info["id"]
access_token = user_info["accessToken"]

headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/json",
    "Referer": "https://ebooks.elibrary.in.pearson.com/",
    "accessToken": access_token,
    "platform": "wr",
    "Origin": "https://ebooks.elibrary.in.pearson.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Connection": "keep-alive",
    "Cookie": cookie_string,
}


def get_signed_token(
    user_id: str,
    book_id: str,
    book_s3_file_path: str,
    headers: dict,
    s: requests.Session,
) -> str:
    _url = f"https://admin.elibrary.in.pearson.com/cs/user/{user_id}/getSignedToken"
    signed_token = s.post(
        url=_url,
        headers=headers,
        data=json.dumps({"bookId": book_id, "s3FilePath": book_s3_file_path}),
    )
    signed_token.raise_for_status()
    return signed_token.text


def download_binary_file(
    session: requests.Session,
    url: str,
    destination: Path,
    headers: dict,
    chunk_size: int = 1024 * 1024,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    with session.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()

        with destination.open("wb") as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)


def download_text_file(
    session: requests.Session,
    url: str,
    destination: Path,
    headers: dict,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    r = session.get(url, headers=headers)
    r.raise_for_status()

    destination.write_text(
        re.sub(r"[^\x00-\x7F]", "", r.text),  # clean up non-printable chars
        encoding="utf-8",
    )


def download_assets_parallel(
    session: requests.Session,
    items: list[str],
    base_url: str,
    output_dir: Path,
    headers: dict,
    binary: bool,
    max_workers: int = 16,
) -> None:
    total = len(items)

    if not total:
        return

    completed = 0
    last_pct = -1

    with ThreadPoolExecutor(max_workers=max_workers) as executor:

        futures = []

        for item in items:
            url = f"{base_url}/{item}"
            destination = output_dir / item

            fn = download_binary_file if binary else download_text_file

            futures.append(
                executor.submit(
                    fn,
                    session,
                    url,
                    destination,
                    headers,
                )
            )

        for future in as_completed(futures):
            future.result()

            completed += 1

            pct = int(completed * 100 / total)

            if pct != last_pct:
                print(
                    f"\r{pct:3d}% ({completed}/{total})",
                    end="",
                    flush=True,
                )
                last_pct = pct

    print()


def main(
    root_dir: Path = Path("book"),
    get_fonts: bool = True,
    get_pages: bool = True,
    get_images: bool = True,
    get_stylesheets: bool = True,
) -> None:
    with requests.Session() as s:

        adapter = HTTPAdapter(
            pool_connections=32,
            pool_maxsize=32,
        )

        s.mount("https://", adapter)
        s.mount("http://", adapter)

        # Fetch library
        library_info = s.post(
            url=f"https://admin.elibrary.in.pearson.com/user/{user_id}/bookshelf/?time={int(time.time())}",
            data=json.dumps({"books": []}),
            headers=headers,
        ).json()

        books = library_info["books"]

        print("Found books:")
        for i, book in enumerate(books, start=1):
            print(
                f"[{i}] {book['title']} @{book['publisher']} " f"(ISBN: {book['isbn']})"
            )

        book_of_interest = books[int(input("Enter your choice: ")) - 1]

        book_id = book_of_interest["id"]
        book_title = book_of_interest["title"]

        book_src_url = book_of_interest["src_url"]
        book_contents_xml_path = book_of_interest["package_doc_path"]

        book_s3_file_path = book_src_url + book_contents_xml_path

        logging.debug(f"{book_id=}, {book_title=}")

        signed_token = get_signed_token(
            user_id,
            book_id,
            book_s3_file_path,
            headers,
            s,
        )

        auth_headers = {
            **headers,
            "Authorization": f"Bearer {signed_token}",
        }

        # Get the contents (content.opf)
        r = s.get(
            url=book_s3_file_path,
            headers=auth_headers,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, features="xml")

        ops_dir = root_dir / "OPS"
        ops_dir.mkdir(parents=True, exist_ok=True)

        (root_dir / "OPS" / "content.opf").write_text(
            r.text,
            encoding="utf-8",
        )

        images = []
        fonts = []
        pages = []
        stylesheets = []
        for item in soup.find_all("item"):
            href = item.get("href")
            if href.startswith("images/"):
                images.append(href[len("images/") :])
            elif href.startswith("fonts/"):
                fonts.append(href[len("fonts/") :])
            elif href.startswith("css/"):
                stylesheets.append(href[len("css/") :])
            elif "xhtml" in href:
                pages.append(href)

        if get_fonts:
            print(f"Downloading {len(fonts)} fonts...")
            download_assets_parallel(
                session=s,
                items=fonts,
                base_url=f"{book_src_url}/OPS/fonts",
                output_dir=ops_dir / "fonts",
                headers=auth_headers,
                binary=True,
            )

        if get_images:
            print(f"Downloading {len(images)} images...")
            download_assets_parallel(
                session=s,
                items=images,
                base_url=f"{book_src_url}/OPS/images",
                output_dir=ops_dir / "images",
                headers=auth_headers,
                binary=True,
            )

        if get_stylesheets:
            print(f"Downloading {len(stylesheets)} stylesheets...")
            download_assets_parallel(
                session=s,
                items=stylesheets,
                base_url=f"{book_src_url}/OPS/css",
                output_dir=ops_dir / "css",
                headers=auth_headers,
                binary=False,
            )

        if get_pages:
            print(f"Downloading {len(pages)} pages...")
            download_assets_parallel(
                session=s,
                items=pages,
                base_url=f"{book_src_url}/OPS",
                output_dir=ops_dir,
                headers=auth_headers,
                binary=False,
            )

    print(f"Done! All downloads should be at {str(root_dir.absolute())}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download Pearson eLibrary books.")

    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("book"),
        help="Output directory (default: book)",
    )

    parser.add_argument(
        "--no-pages",
        "-P",
        action="store_false",
        dest="get_pages",
        help="Do not download XHTML pages",
    )

    parser.add_argument(
        "--no-stylesheets",
        "--no-css",
        "-C",
        action="store_false",
        dest="get_stylesheets",
        help="Do not download stylesheets",
    )

    parser.add_argument(
        "--no-images",
        "-I",
        action="store_false",
        dest="get_images",
        help="Do not download images",
    )

    parser.add_argument(
        "--no-fonts",
        "-F",
        action="store_false",
        dest="get_fonts",
        help="Do not download fonts",
    )

    parser.set_defaults(
        get_pages=True,
        get_stylesheets=True,
        get_images=True,
        get_fonts=True,
    )

    args = parser.parse_args()

    main(
        root_dir=args.output_dir,
        get_pages=args.get_pages,
        get_stylesheets=args.get_stylesheets,
        get_images=args.get_images,
        get_fonts=args.get_fonts,
    )

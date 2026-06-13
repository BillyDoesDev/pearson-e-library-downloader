import requests
import json
import time
import urllib.parse
from bs4 import BeautifulSoup
import re
import logging

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


def main(
    get_fonts: bool = True,
    get_pages: bool = True,
    get_images: bool = True,
    get_stylesheets: bool = True,
) -> None:
    with requests.Session() as s:
        # get all books for this user
        _url = f"https://admin.elibrary.in.pearson.com/user/{user_id}/bookshelf/?time={int(time.time())}"
        library_info = s.post(
            url=_url, data=json.dumps({"books": []}), headers=headers
        ).json()
        books = library_info["books"]

        # target a book of choice
        print("Found books:")
        for i, book in enumerate(books):
            print(
                f"{[i+1]} {book['title']} @{book['publisher']} (ISBN: {book['isbn']})"
            )

        book_of_interest = books[int(input("Enter your choice: ")) - 1]

        book_id = book_of_interest["id"]
        book_title = book_of_interest["title"]

        # The code below gets you a URL in the following format:
        # https://ebooks.elibrary.in.pearson.com/xxx/yyy/ISBN-version
        book_src_url = book_of_interest["src_url"]

        book_contents_xml_path = book_of_interest[
            "package_doc_path"
        ]  # /OPS/content.opf
        book_s3_file_path = book_src_url + book_contents_xml_path
        logging.debug(f"{book_id, book_title = }")

        signed_token = get_signed_token(user_id, book_id, book_s3_file_path, headers, s)

        # get the contents xml (content.opf)
        r = s.get(
            url=book_s3_file_path,
            headers={
                **headers,
                "Authorization": f"Bearer {signed_token}",
            },
        )
        r.raise_for_status()
        # with open("content.opf", "w") as f:
        #     f.write(r.text)

        soup = BeautifulSoup(r.text, features="xml")

        images = []
        fonts = []
        pages = []
        stylesheets = []
        for item in soup.find_all("item"):
            _ = item.get("href")
            # print(_)
            if _.startswith("images/"):
                images.append(_[len("images/") :])
            elif "xhtml" in _:
                pages.append(_)
            elif _.startswith("fonts/"):
                fonts.append(_[len("fonts/") :])
            elif _.startswith("css/"):
                stylesheets.append(_[len("css/") :])

        # get the fonts
        # for font in fonts:
        #     with s.get(f"{book_src_url}/OPS/fonts/{font}", headers=headers, stream=True) as r:
        #         r.raise_for_status()
        #         print(f"Downloading font {font}...")
        #         with open(f"page-x/fonts/{font}", "wb") as f:
        #             for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
        #                 if chunk:
        #                     f.write(chunk)
        #     # break

        # get the pages
        for page in pages:
            r = s.get(
                f"{book_src_url}/OPS/{page}?date={int(time.time()*1000)}",
                headers={
                    **headers,
                    "Authorization": f"Bearer {signed_token}",
                },
            )
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError:
                logging.info("Token expired. Refreshing...")
                signed_token = get_signed_token(
                    user_id, book_id, book_s3_file_path, headers, s
                )
                r = s.get(
                    f"{book_src_url}/OPS/{page}?date={int(time.time()*1000)}",
                    headers={
                        **headers,
                        "Authorization": f"Bearer {signed_token}",
                    },
                )

            print(f"Downloading page {page}...")
            with open(f"page-x/{page}", "w") as f:
                f.write(
                    re.sub(r"[^\x00-\x7F]", "", r.text)
                )  # clean up all non-ascii chars
            break

        # get the images
        # for image in images:
        #     r = s.get(f"{book_src_url}/OPS/images/{image}", headers=headers)
        #     print(f"Downloading image {image}...")
        #     with open(f"page-x/images/{image}", "wb") as f:
        #         f.write(r.content)
        #     # break

        # get the stylesheets
        # for css in stylesheets:
        #     r = s.get(f"{book_src_url}/OPS/css/{css}", headers=headers)
        #     print(f"Downloading stylesheet {css}...")
        #     with open(f"page-x/css/{css}", "w") as f:
        #         f.write(r.text)
        #     # break

    ## takes roughly 7m for 721 pages


if __name__ == "__main__":
    main()

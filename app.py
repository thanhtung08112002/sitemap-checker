import pandas as pd
import streamlit as st

from sitemap_checker import base_url_of, crawl, discover_sitemap_urls, sitemaps_from_common_paths

st.set_page_config(page_title="Sitemap Checker", page_icon="🗺️")
st.title("🗺️ Sitemap Checker")
st.caption("Nhap URL sitemap hoac URL trang web thuong, tool se tu tim va thong ke so URL.")

url = st.text_input("URL", placeholder="https://example.com hoac https://example.com/sitemap.xml")
timeout = st.slider("Timeout (giay)", min_value=5, max_value=60, value=15)
no_discover = st.checkbox("URL truyen vao la sitemap that (khong can tu tim)", value=False)

if st.button("Quet sitemap", type="primary") and url:
    with st.spinner("Dang quet..."):
        start_urls = [url]
        if not no_discover and not url.rstrip("/").lower().endswith(".xml"):
            try:
                start_urls = discover_sitemap_urls(url, timeout=timeout)
                st.info("Da tu tim thay sitemap:\n" + "\n".join(f"- {u}" for u in start_urls))
            except RuntimeError as e:
                st.error(str(e))
                st.stop()

        results = []
        visited = set()
        for start_url in start_urls:
            crawl(start_url, timeout, results, visited)

        all_failed = results and all(r["error"] for r in results)
        if all_failed and not no_discover:
            base = base_url_of(url)
            fallback_urls = [u for u in sitemaps_from_common_paths(base, timeout=timeout) if u not in visited]
            if fallback_urls:
                st.info("Cac sitemap tu robots.txt deu loi, thu tim tiep:\n" + "\n".join(f"- {u}" for u in fallback_urls))
                for start_url in fallback_urls:
                    crawl(start_url, timeout, results, visited)

        if not results:
            st.error("Khong tim thay sitemap nao.")
            st.stop()

        df = pd.DataFrame(results)
        total = df["count"].sum()

        st.subheader("Ket qua")
        st.dataframe(
            df.rename(columns={"sitemap": "Sitemap", "count": "So luong URL", "error": "Loi"})[
                ["Sitemap", "So luong URL", "Loi"]
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.metric("Tong so URL", int(total))

        attachments = df[df["sitemap"].str.contains("attachment", case=False, na=False)]
        if not attachments.empty and total:
            att_count = int(attachments["count"].sum())
            pct = att_count / total * 100
            st.warning(f"attachment-sitemap chiem {att_count}/{int(total)} URL (~{pct:.0f}%).")

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Tai CSV", csv, "sitemap_report.csv", "text/csv")

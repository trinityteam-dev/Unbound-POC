import sys
from pypdf import PdfReader

def main():
    pdf_path = "data/Document Required Checklist - 2025.pdf"
    try:
        reader = PdfReader(pdf_path)
        print(f"Number of pages: {len(reader.pages)}")
        text = ""
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            print(f"--- Page {i+1} ---")
            print(page_text[:1000])  # print start of page
            text += f"\n--- Page {i+1} ---\n" + page_text
        
        with open("data/checklist_extracted.txt", "w", encoding="utf-8") as f:
            f.write(text)
        print("Successfully extracted all text to data/checklist_extracted.txt")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()

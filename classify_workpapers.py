#!/usr/bin/env python3
import os
import sys
import json
import shutil
import tempfile
import subprocess
from pypdf import PdfReader

# Load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise EnvironmentError("OPENROUTER_API_KEY is not set. Add it to your .env file.")

# Helper to find executables
def find_executable(name, default_path):
    path = shutil.which(name)
    if path:
        return path
    if os.path.exists(default_path):
        return default_path
    return name

# Paths to dependencies (defaults match local Mac configuration)
PDFTOPPM_PATH = find_executable("pdftoppm", "/opt/homebrew/bin/pdftoppm")
TESSERACT_PATH = find_executable("tesseract", "/opt/homebrew/bin/tesseract")

SYSTEM_PROMPT = """You are an AI assistant specialized in Australian income tax auditing and Self-Managed Superannuation Fund (SMSF) work paper filing.
Your task is to classify a document's extracted text or OCR text into exactly one of the following 11 categories:

1. Audit Invoice
2. Accountancy - $XXX
3. Tax Statement Metrics
4. Income Tax
5. Income Tax Activity
6. Bank Statement - [Account no ]
7. Portfolio Valuation at DD.MM.YY
8. Ordr Mint Transation Listing
9. F25 Periodic Statement Metrics
10. Delisted DSE
11. Total Super annuation balance

You must return a valid JSON object matching this structure:
{
  "category": "One of the 11 categories listed above exactly.",
  "account_number": "For 'Bank Statement - [Account no ]', extract the bank account number (usually 8-15 digits, strip formatting). Otherwise, set to null.",
  "amount": "For 'Accountancy - $XXX', extract the invoice total amount (e.g. '270.41'). Otherwise, set to null.",
  "date": "For 'Portfolio Valuation at DD.MM.YY', extract the valuation date and format it as DD.MM.YY (e.g., '30.06.25'). Otherwise, set to null.",
  "reasoning": "A concise explanation of why this document matches the chosen category."
}
"""

def extract_pdf_text(filepath):
    """Try to extract text from a PDF file using pypdf."""
    try:
        reader = PdfReader(filepath)
        text = ""
        # Read up to 3 pages for classification context
        num_pages = len(reader.pages)
        for i in range(min(3, num_pages)):
            page_text = reader.pages[i].extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error reading PDF {filepath} with pypdf: {e}", file=sys.stderr)
        return ""

def ocr_pdf_first_page(filepath):
    """Fall back to rendering the first page and performing OCR using pdftoppm and tesseract."""
    print(f"Attempting OCR on first page of: {os.path.basename(filepath)}")
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1. Render first page to PNG
        prefix = os.path.join(temp_dir, "page")
        cmd_render = [
            PDFTOPPM_PATH,
            "-png",
            "-f", "1",
            "-l", "1",
            "-r", "150",
            filepath,
            prefix
        ]
        
        try:
            subprocess.run(cmd_render, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"pdftoppm failed: {e.stderr.decode(errors='replace').strip()}")
        except FileNotFoundError:
            raise RuntimeError(f"pdftoppm not found at: {PDFTOPPM_PATH}. Please check installation.")

        # Find the rendered PNG file
        png_files = [f for f in os.listdir(temp_dir) if f.endswith(".png")]
        if not png_files:
            raise RuntimeError("pdftoppm did not generate any PNG files")
        
        png_path = os.path.join(temp_dir, png_files[0])

        # 2. Perform OCR using tesseract
        ocr_out_base = os.path.join(temp_dir, "ocr_result")
        cmd_ocr = [
            TESSERACT_PATH,
            png_path,
            ocr_out_base
        ]
        
        try:
            subprocess.run(cmd_ocr, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"tesseract failed: {e.stderr.decode(errors='replace').strip()}")
        except FileNotFoundError:
            raise RuntimeError(f"tesseract not found at: {TESSERACT_PATH}. Please check installation.")

        # Read the OCR text output
        ocr_txt_path = ocr_out_base + ".txt"
        if os.path.exists(ocr_txt_path):
            with open(ocr_txt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        else:
            raise RuntimeError("Tesseract output file not found")

def query_openrouter_classification(text_content):
    """Query OpenRouter API using grok-4.20 to classify the document text."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    import requests
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/google/doc-intelligence",
        "X-Title": "SMSF Document Classifier"
    }
    
    # Send up to 3500 characters of text to stay within reasonable limits
    doc_snippet = text_content[:3500]
    
    payload = {
        "model": "x-ai/grok-4.20",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Document content:\n```\n{doc_snippet}\n```\n\nClassify this document."}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=45)
        response.raise_for_status()
        res_data = response.json()
        
        choices = res_data.get("choices", [])
        if not choices:
            raise ValueError(f"No choices returned from OpenRouter. Response: {res_data}")
            
        message_content = choices[0]["message"]["content"]
        return json.loads(message_content)
    except Exception as e:
        print(f"OpenRouter API Error: {e}", file=sys.stderr)
        # Attempt to inspect response if it was an HTTP error
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Response details: {response.text}", file=sys.stderr)
        return None

def determine_target_filename(classification, original_name):
    """Determine the renamed filename based on the classification output."""
    category = classification.get("category")
    
    if not category:
        return f"Unclassified_{original_name}"
        
    category_clean = category.strip()
    
    if category_clean == "Audit Invoice":
        return "Audit Invoice.pdf"
        
    elif category_clean.startswith("Accountancy"):
        amount = classification.get("amount")
        if amount:
            # Ensure it has a $ prefix and matches the requested format
            amount_str = str(amount).strip().replace("$", "")
            return f"Accountancy - ${amount_str}.pdf"
        else:
            return "Accountancy.pdf"
            
    elif category_clean == "Tax Statement Metrics":
        return "Tax Statement Metrics.pdf"
        
    elif category_clean == "Income Tax":
        return "Income Tax.pdf"
        
    elif category_clean == "Income Tax Activity":
        return "Income Tax Activity.pdf"
        
    elif category_clean.startswith("Bank Statement"):
        account_number = classification.get("account_number")
        if account_number:
            acc_clean = str(account_number).strip()
            return f"Bank Statement - {acc_clean}.pdf"
        else:
            return "Bank Statement.pdf"
            
    elif category_clean.startswith("Portfolio Valuation"):
        date_val = classification.get("date")
        if date_val:
            date_clean = str(date_val).strip()
            return f"Portfolio Valuation at {date_clean}.pdf"
        else:
            return "Portfolio Valuation.pdf"
            
    elif category_clean == "Ordr Mint Transation Listing":
        return "Ordr Mint Transation Listing.pdf"
        
    elif category_clean == "F25 Periodic Statement Metrics":
        return "F25 Periodic Statement Metrics.pdf"
        
    elif category_clean == "Delisted DSE":
        return "Delisted DSE.pdf"
        
    elif category_clean == "Total Super annuation balance":
        return "Total Super annuation balance.pdf"
        
    else:
        # Fallback for unrecognized categories
        print(f"Warning: Category '{category}' not standard. Saving as custom name.", file=sys.stderr)
        # Sanitize category for filename
        sanitized_cat = "".join([c if c.isalnum() or c in " -_$" else "_" for c in category_clean])
        return f"{sanitized_cat}.pdf"

def get_unique_filepath(dest_dir, filename):
    """Ensure we do not overwrite files by appending counter suffixes if there's a collision."""
    name, ext = os.path.splitext(filename)
    counter = 1
    new_filename = filename
    while os.path.exists(os.path.join(dest_dir, new_filename)):
        new_filename = f"{name}_{counter}{ext}"
        counter += 1
    return os.path.join(dest_dir, new_filename)

def main():
    # Check for OpenRouter API Key first
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("CRITICAL: OPENROUTER_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please set it using: export OPENROUTER_API_KEY='your-key-here'", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python3 classify_workpapers.py <input_folder_path> [output_parent_path]")
        sys.exit(1)
        
    input_folder = os.path.abspath(sys.argv[1])
    if not os.path.isdir(input_folder):
        print(f"Error: Input path is not a directory: {input_folder}", file=sys.stderr)
        sys.exit(1)
        
    # Determine output folder
    output_parent = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.getcwd()
    output_dir = os.path.join(output_parent, "output", "workpaper")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Scanning directory: {input_folder}")
    print(f"Output directory: {output_dir}")
    print("=" * 60)
    
    # Recursively find all PDF files
    pdf_files = []
    for root, _, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, file))
                
    if not pdf_files:
        print("No PDF files found in the input folder.")
        sys.exit(0)
        
    print(f"Found {len(pdf_files)} PDF files to classify.")
    
    success_count = 0
    failure_count = 0
    
    for idx, filepath in enumerate(pdf_files, 1):
        filename = os.path.basename(filepath)
        print(f"\n[{idx}/{len(pdf_files)}] Processing: {filename}")
        
        # 1. Extract text
        text = extract_pdf_text(filepath)
        
        # 2. Fall back to OCR if text is sparse (scanned PDF)
        if len(text.strip()) < 50:
            print("  PDF contains very little text. Running OCR fallback...")
            try:
                text = ocr_pdf_first_page(filepath)
                print(f"  OCR successful (extracted {len(text)} characters from first page)")
            except Exception as e:
                print(f"  OCR Fallback Failed: {e}", file=sys.stderr)
                text = ""
                
        if not text.strip():
            print(f"  Skipping: Could not extract any text or OCR content from {filename}")
            failure_count += 1
            continue
            
        # 3. Query OpenRouter
        print("  Querying Grok-4.20 classification...")
        classification = query_openrouter_classification(text)
        
        if not classification:
            print(f"  Skipping: API classification failed for {filename}")
            failure_count += 1
            continue
            
        print(f"  Classification: {classification.get('category')}")
        if classification.get("reasoning"):
            print(f"  Reasoning: {classification.get('reasoning')}")
            
        # 4. Copy and Rename
        target_name = determine_target_filename(classification, filename)
        dest_filepath = get_unique_filepath(output_dir, target_name)
        
        try:
            shutil.copy2(filepath, dest_filepath)
            print(f"  Copied and renamed to: {os.path.basename(dest_filepath)}")
            success_count += 1
        except Exception as e:
            print(f"  Error copying file: {e}", file=sys.stderr)
            failure_count += 1
            
    print("\n" + "=" * 60)
    print("Classification Summary:")
    print(f"  Total processed: {len(pdf_files)}")
    print(f"  Successfully classified and copied: {success_count}")
    print(f"  Failed: {failure_count}")
    print(f"  All results saved in: {output_dir}")
    print("=" * 60)

if __name__ == "__main__":
    main()

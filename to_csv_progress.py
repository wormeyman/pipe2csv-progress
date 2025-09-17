#!/usr/bin/env python3
import sys, os, re, csv, time, argparse

def human(n):
		for unit in ["", "K", "M", "B"]:
				if abs(n) < 1000:
						return f"{n:.0f}{unit}"
				n /= 1000.0
		return f"{n:.1f}T"

def stream_lines_with_progress(path, encoding="cp1252", chunk_size=1024*1024):
		"""
		Read the input file in binary, decode in cp1252, normalize <br> -> \n,
		and yield logical non-empty text lines. Yields (line, bytes_read_so_far).
		Because cp1252 is single-byte, len(chunk) bytes read maps 1:1 to bytes consumed.
		"""
		br_re = re.compile(r"<br\s*/?>", re.IGNORECASE)
		bytes_read = 0

		with open(path, "rb") as fb:
				carry = ""
				while True:
						chunk = fb.read(chunk_size)
						if not chunk:
								break
						bytes_read += len(chunk)
						text = chunk.decode(encoding, errors="strict")
						carry += text
						# Normalize breaks then split
						carry = br_re.sub("\n", carry)
						*lines, carry = carry.split("\n")
						for ln in lines:
								ln = ln.strip()
								if ln:
										yield ln, bytes_read
				# Flush remainder
				carry = carry.strip()
				if carry:
						yield carry, bytes_read

def main():
		ap = argparse.ArgumentParser(description="Convert pipe+<br> export to RFC-4180 CSV with accurate progress.")
		ap.add_argument("inp", help="Input text file (pipe-delimited, <br> line breaks, likely CP1252)")
		ap.add_argument("out", help="Output CSV file (UTF-8)")
		ap.add_argument("--encoding", default="cp1252", help="Source encoding (default: cp1252)")
		ap.add_argument("--tick", type=int, default=100_000, help="Print progress every N rows (default: 100000)")
		ap.add_argument("--chunk", type=int, default=1024*1024, help="Read chunk size in bytes (default: 1 MiB)")
		args = ap.parse_args()

		try:
				total_bytes = os.path.getsize(args.inp)
		except OSError:
				total_bytes = None

		start = time.time()

		line_iter = stream_lines_with_progress(args.inp, encoding=args.encoding, chunk_size=args.chunk)

		# Header
		try:
				header_line, bytes_read = next(line_iter)
		except StopIteration:
				print("Input appears empty after normalization.", file=sys.stderr)
				sys.exit(1)
		header = [c.strip() for c in header_line.split("|")]

		with open(args.out, "w", newline="", encoding="utf-8") as csvfile:
				w = csv.writer(csvfile)
				w.writerow(header)
				rows = 0

				for ln, bytes_read in line_iter:
						row = [c.strip() for c in ln.split("|")]
						w.writerow(row)
						rows += 1

						if rows % args.tick == 0:
								now = time.time()
								elapsed = max(now - start, 1e-6)
								rps = rows / elapsed
								pct = ""
								eta = ""
								if total_bytes:
										p = (bytes_read / total_bytes) * 100.0
										pct = f" {p:5.1f}%"
										if bytes_read > 0:
												total_time = elapsed * (total_bytes / bytes_read)
												eta_sec = max(total_time - elapsed, 0)
												eta = f" ETA {int(eta_sec//3600):02d}:{int((eta_sec%3600)//60):02d}:{int(eta_sec%60):02d}"
								print(f"[{time.strftime('%H:%M:%S')}] rows={human(rows)} rate={rps:,.0f}/s{pct}{eta}")

		elapsed = time.time() - start
		rate = (rows / elapsed) if elapsed > 0 else 0.0
		print(f"Done. Wrote {rows:,} data rows (+ header) to {args.out} in {elapsed:,.1f}s, {rate:,.0f} rows/s.")

if __name__ == "__main__":
		try:
				main()
		except UnicodeDecodeError as e:
				print("Encoding error. Try --encoding cp1252 or latin-1.", file=sys.stderr)
				raise
import csv
import hashlib
import io
import random
from pathlib import Path
from typing import TypedDict

import streamlit as st


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"


class QuestionItem(TypedDict):
	question_number: str
	question: str
	answers: list[str]
	image_path: str


def decode_csv(file_bytes: bytes) -> str:
	for encoding in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return file_bytes.decode(encoding)
		except UnicodeDecodeError:
			continue
	raise ValueError(
		"Could not decode the CSV file. Use UTF-8, Windows-1252, or Latin-1."
	)


def parse_questions(file_bytes: bytes) -> tuple[list[QuestionItem], int]:
	csv_text = decode_csv(file_bytes)
	sample = csv_text[:2048]

	try:
		dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
	except csv.Error:
		dialect = csv.excel

	reader = csv.reader(io.StringIO(csv_text), dialect=dialect)
	rows = [row for row in reader if any(cell.strip() for cell in row)]

	if not rows:
		raise ValueError("The CSV file is empty.")

	first_row = [cell.strip().lower() for cell in rows[0]]
	has_number_column = len(first_row) >= 2 and first_row[1] in {"question", "frage"}

	if has_number_column:
		start_row = 1
	else:
		first_cell = first_row[0]
		start_row = 1 if first_cell in {"question", "frage"} else 0
		if start_row == 0 and rows[0][0].strip().isdigit():
			has_number_column = True

	questions: list[QuestionItem] = []
	skipped_rows = 0

	for row_index, row in enumerate(rows[start_row:], start=1):
		column_offset = 1 if has_number_column else 0
		if len(row) < 5 + column_offset:
			skipped_rows += 1
			continue

		question_number = row[0].strip() if has_number_column else str(row_index)
		question_text = row[column_offset].strip()
		answers = [cell.strip() for cell in row[column_offset + 1 : column_offset + 5]]
		image_path = row[column_offset + 5].strip() if len(row) >= column_offset + 6 else ""

		if not question_text or any(not answer for answer in answers):
			skipped_rows += 1
			continue

		questions.append(
			{
				"question_number": question_number,
				"question": question_text,
				"answers": answers,
				"image_path": image_path,
			}
		)

	if not questions:
		raise ValueError("No valid question rows were found in the CSV.")

	return questions, skipped_rows


def find_csv_files(data_dir: Path) -> list[Path]:
	return sorted(path for path in data_dir.glob("*.csv") if path.is_file())


def resolve_image_path(image_path_value: str) -> Path | None:
	image_path_value = image_path_value.strip()
	if not image_path_value:
		return None

	raw_path = Path(image_path_value)
	candidates: list[Path] = []

	if raw_path.is_absolute():
		candidates.append(raw_path)
	else:
		candidates.append(IMAGE_DIR / raw_path)
		candidates.append(DATA_DIR / raw_path)

		parts = raw_path.parts
		if parts and parts[0].lower() == "images":
			candidates.append(IMAGE_DIR / Path(*parts[1:]))
		if len(parts) >= 2 and parts[0].lower() == "data" and parts[1].lower() == "images":
			candidates.append(IMAGE_DIR / Path(*parts[2:]))

	for candidate in candidates:
		if candidate.exists():
			return candidate

	return candidates[0] if candidates else None


def clear_choice_keys() -> None:
	for key in list(st.session_state.keys()):
		if key.startswith("choice_"):
			del st.session_state[key]


def reset_quiz_runtime() -> None:
	total_questions = len(st.session_state["questions"])
	st.session_state["question_order"] = random.sample(
		range(total_questions), total_questions
	)
	st.session_state["current_question_pos"] = 0
	st.session_state["score"] = 0
	st.session_state["checked_questions"] = {}
	st.session_state["shuffled_answer_order"] = {}
	clear_choice_keys()


def load_file_into_state(file_bytes: bytes) -> None:
	questions, skipped_rows = parse_questions(file_bytes)
	st.session_state["questions"] = questions
	st.session_state["skipped_rows"] = skipped_rows
	reset_quiz_runtime()


def render_radio_feedback(
	display_order: list[int],
	selected_index: int,
	is_correct: bool,
) -> None:
	correct_position = display_order.index(0) + 1
	wrong_position = None
	if not is_correct:
		wrong_position = display_order.index(selected_index) + 1

	base_selector = "div[data-testid='stRadio'] label[data-baseweb='radio']"
	css_rules = [
		"<style>",
		f"{base_selector} {{ border: 1px solid transparent; border-radius: 0.65rem; padding: 0.35rem 0.55rem; transition: none; }}",
		f"{base_selector} > div:last-child {{ width: 100%; }}",
	]

	correct_selector = f"{base_selector}:nth-of-type({correct_position})"
	css_rules.extend(
		[
			f"{correct_selector} {{ background-color: rgba(22, 163, 74, 0.12) !important; border-color: rgba(22, 163, 74, 0.45) !important; }}",
			f"{correct_selector} > div:last-child {{ color: rgb(22, 163, 74) !important; font-weight: 600 !important; }}",
			f"{correct_selector} > div:first-child {{ color: rgb(22, 163, 74) !important; }}",
		]
	)

	if wrong_position is not None:
		wrong_selector = f"{base_selector}:nth-of-type({wrong_position})"
		css_rules.extend(
			[
				f"{wrong_selector} {{ background-color: rgba(220, 38, 38, 0.12) !important; border-color: rgba(220, 38, 38, 0.45) !important; }}",
				f"{wrong_selector} > div:last-child {{ color: rgb(220, 38, 38) !important; font-weight: 600 !important; }}",
				f"{wrong_selector} > div:first-child {{ color: rgb(220, 38, 38) !important; }}",
			]
		)

	css_rules.append("</style>")
	st.markdown("\n".join(css_rules), unsafe_allow_html=True)


st.set_page_config(page_title="CSV Question Trainer", layout="centered")

IMAGE_DIR.mkdir(parents=True, exist_ok=True)
csv_files = find_csv_files(DATA_DIR)

if not csv_files:
	st.error("No CSV files found in `data/`. Add a question CSV file and rerun.")
	st.stop()

csv_names = [path.name for path in csv_files]
preferred_csv_name = "Fragesammlung_questions_answers.csv"
default_csv_name = preferred_csv_name if preferred_csv_name in csv_names else csv_names[0]

if (
	"selected_csv_name" not in st.session_state
	or st.session_state["selected_csv_name"] not in csv_names
):
	st.session_state["selected_csv_name"] = default_csv_name

def quiz_label(csv_name: str) -> str:
	return Path(csv_name).stem.replace("_", " ")


with st.sidebar:
	st.subheader("Quiz")
	if len(csv_names) > 1:
		selected_csv_name = st.selectbox(
			"Choose quiz",
			options=csv_names,
			format_func=quiz_label,
			key="selected_csv_name",
		)
	else:
		selected_csv_name = csv_names[0]
		st.session_state["selected_csv_name"] = selected_csv_name
		st.caption(f"Only one quiz available: {quiz_label(selected_csv_name)}")

selected_csv_path = DATA_DIR / selected_csv_name

try:
	file_bytes = selected_csv_path.read_bytes()
except OSError as exc:
	st.error(f"Could not read `{selected_csv_name}`: {exc}")
	st.stop()

file_signature = (
	f"{selected_csv_path.name}:{hashlib.sha256(file_bytes).hexdigest()}"
)

if st.session_state.get("file_signature") != file_signature:
	try:
		load_file_into_state(file_bytes)
	except ValueError as exc:
		st.error(str(exc))
		st.stop()
	st.session_state["file_signature"] = file_signature

questions: list[QuestionItem] = st.session_state["questions"]
total_questions = len(questions)
answered_count = len(st.session_state["checked_questions"])
score = st.session_state["score"]
current_pos = st.session_state["current_question_pos"]
question_order = st.session_state["question_order"]
question_numbers_in_file_order = [question["question_number"] for question in questions]
question_number_positions = {
	questions[question_index]["question_number"]: order_position
	for order_position, question_index in enumerate(question_order)
}
all_question_numbers_are_numeric = all(
	question_number.isdigit() for question_number in question_numbers_in_file_order
)

if current_pos < total_questions:
	current_question_number = questions[question_order[current_pos]]["question_number"]
else:
	current_question_number = questions[question_order[-1]]["question_number"]

with st.sidebar:
	st.subheader("Progress")
	st.write(f"Score: {score}/{answered_count}")
	st.write(f"Question: {min(current_pos + 1, total_questions)}/{total_questions}")

	st.subheader("Jump")
	with st.form("jump_to_question_form"):
		if all_question_numbers_are_numeric:
			numeric_question_numbers = [
				int(question_number) for question_number in question_numbers_in_file_order
			]
			target_question_number = st.number_input(
				"Question number",
				min_value=min(numeric_question_numbers),
				max_value=max(numeric_question_numbers),
				value=int(current_question_number),
				step=1,
			)
			target_question_key = str(target_question_number)
		else:
			target_question_key = st.selectbox(
				"Question number",
				options=question_numbers_in_file_order,
				index=question_numbers_in_file_order.index(current_question_number),
			)

		jump_submitted = st.form_submit_button("Go to question")

	if jump_submitted:
		target_position = question_number_positions.get(target_question_key)
		if target_position is None:
			st.warning(f"Question {target_question_key} was not found.")
		else:
			st.session_state["current_question_pos"] = target_position
			st.rerun()

	if st.button("Restart quiz"):
		reset_quiz_runtime()
		st.rerun()

if st.session_state["skipped_rows"] > 0:
	st.warning(f"Skipped {st.session_state['skipped_rows']} invalid row(s).")

if current_pos >= total_questions:
	percentage = (score / total_questions) * 100
	st.success(f"Finished. Final score: {score}/{total_questions} ({percentage:.1f}%).")
	if st.button("Start again", type="primary"):
		reset_quiz_runtime()
		st.rerun()
	st.stop()

question_index = question_order[current_pos]
question = questions[question_index]
answers = question["answers"]

st.subheader(f"Question {question['question_number']}")
st.write(question["question"])

resolved_image_path = resolve_image_path(question["image_path"])
if resolved_image_path is not None:
	if resolved_image_path.exists():
		st.image(str(resolved_image_path), width=360)
	else:
		st.caption(f"Image file not found yet: {question['image_path']}")

if question_index not in st.session_state["shuffled_answer_order"]:
	answer_order = [0, 1, 2, 3]
	random.shuffle(answer_order)
	st.session_state["shuffled_answer_order"][question_index] = answer_order

display_order = st.session_state["shuffled_answer_order"][question_index]

choice_key = f"choice_{question_index}"
checked_entry = st.session_state["checked_questions"].get(question_index)
already_checked = checked_entry is not None

checked_is_correct = False
checked_selected_index: int | None = None
if already_checked:
	if isinstance(checked_entry, dict):
		checked_is_correct = bool(checked_entry.get("is_correct", False))
		checked_selected_index = checked_entry.get("selected_index")
	else:
		# Compatibility for existing sessions created before selected answers were stored.
		checked_is_correct = bool(checked_entry)
		checked_selected_index = st.session_state.get(choice_key)

	if checked_selected_index is not None and choice_key not in st.session_state:
		st.session_state[choice_key] = checked_selected_index

selected_answer_index = st.radio(
	"Choose one answer:",
	options=display_order,
	format_func=lambda idx: answers[idx],
	index=None,
	key=choice_key,
	disabled=already_checked,
)

if not already_checked:
	if st.button("Check answer", type="primary"):
		if selected_answer_index is None:
			st.warning("Please select an answer before checking.")
		else:
			is_correct = selected_answer_index == 0
			st.session_state["checked_questions"][question_index] = {
				"is_correct": is_correct,
				"selected_index": selected_answer_index,
			}
			if is_correct:
				st.session_state["score"] += 1
			st.rerun()
else:

	if checked_selected_index is not None:
		render_radio_feedback(
			display_order=display_order,
			selected_index=checked_selected_index,
			is_correct=checked_is_correct,
		)

	if st.button("Next question", type="primary"):
		st.session_state["current_question_pos"] += 1
		st.rerun()
from openai import OpenAI

# OpenAI API 연결
client = OpenAI()

print("=== 나만의 AI 챗봇 ===")
print("종료하려면 '종료'를 입력하세요.\n")

# 이전 대화 내용을 기억하기 위한 변수
previous_id = None

while True:
    question = input("나: ").strip()

    if question == "종료":
        print("챗봇을 종료합니다.")
        break

    if not question:
        continue

    try:
        params = {
            "model": "gpt-4.1-mini",
            "instructions": "한국어로 쉽고 친절하게 답변하세요.",
            "input": question
        }

        if previous_id:
            params["previous_response_id"] = previous_id

        response = client.responses.create(**params)

        print("AI:", response.output_text, "\n")
        previous_id = response.id

    except Exception as e:
        print("오류가 발생했습니다:", e)

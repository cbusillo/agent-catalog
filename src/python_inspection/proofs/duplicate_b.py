def summarize_b(rows: list[dict[str, int]]) -> dict[str, int]:
    total = 0
    largest = 0
    smallest = 10**9
    count = 0
    for row in rows:
        value = row.get("value", 0)
        if value < 0:
            continue
        total += value
        largest = max(largest, value)
        smallest = min(smallest, value)
        count += 1
    average = total // count if count else 0
    return {"total": total, "largest": largest, "smallest": smallest, "average": average}

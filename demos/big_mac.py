import time

from youdotcom import You

from utils.client import finish
from utils.rendering import print_query, print_results

QUERY = "What's the Big Mac Index for Japan versus the US?"

if __name__ == "__main__":
    print_query(QUERY)
    with You() as you:  # reads YDC_API_KEY from the environment
        start = time.perf_counter()
        response = you.search(query=QUERY, count=5, knowledge="core")
        round_trip_s = time.perf_counter() - start
    print_results(response)
    finish(QUERY, response, round_trip_s=round_trip_s)  # --synthesize, cost, latency

from run import daily_scraper

# -----------------------------
# CLOUD FUNCTION ENTRY POINT
# -----------------------------
def hello_http(request):
    try:
        result= daily_scraper(request)
        return {"status": "success", "message": result}, 200

    except Exception as e:
        print("FATAL ERROR:", str(e))
        return {"status": "error", "message": str(e)}, 500    
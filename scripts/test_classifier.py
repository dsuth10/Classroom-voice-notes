import os
import json
import httpx
from pathlib import Path
from app.config.settings import SettingsManager
from app.ollama_router.classifier import OllamaClassifier

def main():
    print("=== Classroom Voice Notes Classification Test Utility ===")
    
    # Load settings
    from app.utils.paths import get_config_path
    config_path = get_config_path()
    print(f"Loading settings from: {config_path}")
    
    # We can use SettingsManager directly
    manager = SettingsManager()
    ollama_url = manager.get("ollama_url") or "http://localhost:11434"
    model = manager.get("fast_model") or "qwen3.5:latest"
    
    print(f"Ollama URL: {ollama_url}")
    print(f"Ollama Model: {model}")
    
    # 1. Check if Ollama is running and list models
    print("\n--- 1. Checking Ollama Server Connection ---")
    try:
        resp = httpx.get(f"{ollama_url}/api/tags", timeout=5.0)
        if resp.status_code == 200:
            models_data = resp.json()
            models = [m["name"] for m in models_data.get("models", [])]
            print(f"Connection OK! Installed models on your machine: {models}")
            if model not in models:
                print(f"WARNING: The configured model '{model}' was not found in the installed models list.")
                print("Ollama might attempt to pull it automatically on first run, which can take several minutes and cause timeouts.")
        else:
            print(f"Error checking tags: HTTP {resp.status_code}")
    except Exception as e:
        print(f"CRITICAL: Failed to connect to Ollama at {ollama_url}.")
        print("Is the Ollama application running on your computer? (Check your Windows system tray or run 'ollama serve')")
        print(f"Details: {e}")
        return

    # 2. Setup classifier
    classifier = OllamaClassifier(url=ollama_url, model=model)
    
    # 3. Choose test mode
    import sys
    
    test_cases = []
    choice = None
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--suite":
            print("\nRunning standard sample suite from command-line flag...")
            choice = "1"
        else:
            print(f"\nClassifying custom text from command-line argument...")
            test_cases.append(("Command Line Input", arg))
    else:
        print("\n--- 2. Choose Test Mode ---")
        print("1) Test standard sample suite (runs multiple test categories)")
        print("2) Enter a custom transcript interactively")
        
        try:
            choice = input("Select an option (1 or 2): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return
    
    if choice == "2":
        try:
            custom_text = input("\nEnter custom transcript to classify: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            return
        if not custom_text:
            print("No text entered. Exiting.")
            return
        test_cases.append(("Custom Input", custom_text))
    elif choice == "1":
        test_cases = [
            ("Behaviour Note", "Alex was very disruptive today. He threw a paper airplane and refused to sit down."),
            ("Maths Homework", "For maths homework tonight, please complete worksheet 4 on long division."),
            ("English Homework", "For English tomorrow, please make sure you read chapter 3 of the novel and draft a character profile."),
            ("Science Activity", "In science today, we observed the chemical reaction between vinegar and baking soda to demonstrate gas production."),
            ("HASS Mapping", "For geography and history, we are going to look at the first fleet and map their journey from Portsmouth to Botany Bay."),
            ("Digital Technologies", "For digital technologies, we will start writing some simple pseudocode blocks to explain sorting algorithms."),
            ("Design Technologies", "For design technologies, students need to draw a prototype design of their sustainable food package."),
            ("Reminder", "Remember to print the worksheets for tomorrow's science lesson before 8:30 AM."),
            ("Email Draft", "Email to parent: Dear Mrs. Smith, I wanted to follow up on our conversation regarding Tommy's reading progress."),
            ("Agent Task", "Add a new task: update the seating chart to move Sarah to the front row."),
            ("General Note", "The school assembly has been moved to Thursday afternoon due to the weather.")
        ]
        
    print(f"\n--- 3. Running Classifications (Timeout is 30.0s) ---")
    for name, transcript in test_cases:
        print(f"\nEvaluating Category: {name}")
        print(f"Transcript: \"{transcript}\"")
        
        # We want to see the RAW output from Ollama to debug any format/prompt issues
        print("Sending request to Ollama...")
        prompt = f"""
        Classify this classroom voice note. Respond ONLY with a JSON object.
        JSON format:
        {{
            "category": "student_note" | "behaviour_note" | "maths_note" | "english_note" | "science_note" | "hass_note" | "digitech_note" | "designtech_note" | "reminder" | "email_draft" | "agent_task" | "general_note",
            "sensitivity": "student_sensitive" | "teacher_private" | "non_sensitive",
            "confidence": 0.0 to 1.0
        }}
        
        Category definitions:
        - student_note: general observations or info about a specific student
        - behaviour_note: student behaviour or discipline incidents
        - maths_note: mathematics lessons, activities, or homework
        - english_note: English, reading, spelling, writing, or literature
        - science_note: science lessons, experiments, or activities
        - hass_note: Humanities and Social Sciences (history, geography, civics, first fleet)
        - digitech_note: Digital Technologies (coding, computers, algorithms, pseudocode)
        - designtech_note: Design Technologies (designing, prototypes, engineering, food/material packages)
        - reminder: reminders for the teacher (e.g. print worksheets, prep materials)
        - email_draft: drafts or notes of emails to parents or staff
        - agent_task: direct actions for the AI assistant
        - general_note: other administrative or classroom notes
        
        Transcript: "{transcript}"
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        
        try:
            import time
            start_time = time.time()
            response = httpx.post(f"{ollama_url}/api/generate", json=payload, timeout=30.0)
            elapsed = time.time() - start_time
            
            if response.status_code != 200:
                print(f"Error: Ollama returned status {response.status_code}")
                continue
                
            resp_data = response.json()
            raw_response = resp_data.get("response", "").strip()
            if not raw_response and "thinking" in resp_data:
                raw_response = resp_data.get("thinking", "").strip()
                
            # Clean/extract the JSON substring if the model wrapped it in markdown or conversation
            json_str = raw_response
            start_idx = raw_response.find('{')
            end_idx = raw_response.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = raw_response[start_idx:end_idx + 1]
                
            print(f"Time taken: {elapsed:.2f} seconds")
            print(f"Raw Ollama Response String: {repr(raw_response)}")
            
            try:
                parsed_json = json.loads(json_str)
                print(f"Parsed JSON successfully: {json.dumps(parsed_json, indent=2)}")
            except json.JSONDecodeError as je:
                print(f"Parsing ERROR: Failed to parse raw string as JSON: {je}")
                
        except Exception as e:
            print(f"Request failed: {e}")

if __name__ == "__main__":
    main()

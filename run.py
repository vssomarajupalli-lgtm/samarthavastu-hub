import os

def main():
    print("="*50)
    print("   🌟 Samartha Vastu - Automation Launcher 🌟")
    print("="*50)
    print("[1] Image Publishing (Old Method - Thumbnails)")
    print("[2] Video Publishing (New Method - 1-Minute Reels)")
    print("="*50)
    
    choice = input("Enter your choice (1 or 2): ").strip()
    
    if choice == '1':
        print("\n[INFO] Starting Image Publishing...")
        os.system("python auto_publisher.py")
    elif choice == '2':
        print("\n[INFO] Starting Video Publishing...")
        if os.path.exists("video_publisher.py"):
            os.system("python video_publisher.py")
        else:
            print("[INFO] video_publisher.py not found.")
    else:
        print("\n[ERROR] Invalid choice. Exiting.")

if __name__ == "__main__":
    main()
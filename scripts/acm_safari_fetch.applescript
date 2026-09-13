on run argv
    set crawlWindowId to (item 1 of argv) as integer
    set targetURL to item 2 of argv
    set loadTimeout to (item 3 of argv) as real
    tell application "Safari"
        set crawlTab to current tab of window id crawlWindowId
        -- Clear the previous document so its HTML cannot be mistaken for this URL.
        set URL of crawlTab to "about:blank"
        set clearedPage to false
        repeat 50 times
            if URL of crawlTab is "about:blank" and (source of crawlTab) does not contain "awards-winners__citation" then
                set clearedPage to true
                exit repeat
            end if
            delay 0.1
        end repeat
        if not clearedPage then error "Could not clear the previous page"
        set URL of crawlTab to targetURL
        repeat (round (loadTimeout * 2) rounding up) times
            delay 0.5
            set loadedURL to URL of crawlTab
            try
                set pageHTML to source of crawlTab
                if loadedURL is targetURL and pageHTML contains "</html>" then
                    return loadedURL & linefeed & pageHTML
                end if
            end try
        end repeat
        error "Timed out waiting for complete HTML at " & targetURL
    end tell
end run

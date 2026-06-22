GOAL:

The goal is to update the existing database with the latest and historical earnings call transcripts of the stocks in av_financials using the AV API.

Currently, the database is used by the Finview AI Researcher and Earnings summary feature. 

To find out the latest earnings call transcript available, you can use the latest reported quarter in av_financials. However if the latest quarter in av_financials is older than 60 days in the event that there has been a earnings call after the last financial quarter in av_financials, we should also check if there is a earnings call transcript for the quarter following the latest quarter in av_financials. For example, if the latest quarter in av_financials is 2026Q1 and the quarter ended on 3/31/2026 and today is 7/1/2026, we should check whether the AV API as a earnings call transcript for 2026Q2. We should use this method only to initially backfill the earnings call transcript database.

Going forward, we can test whether there is a new earnings call transcript by looking at the date of previous earnings call transcript.

If possible the earnings call transcript should track the earnings call date and the date that the earningls call transcript was downloaded

We would like to backfill with all the earnings call transcripts available in AV. AV claims that provides up to 15 years of earnings call transcripts. However the history of earnings calls transcripts will significantly vary by stock.

Before doing any planing or implementation, review the existing code for the Earnings summary feature in Finview.

Also create a script to update the earnings call transcript on a weekly basis.

If the user runs Earnings summary feature in Finview and the earnings call transcript is not in the database, the Earnings summary code will download the earnings call transcipt into the database

Please create a PLAN.md with testable phases. As each phase is implemented, it should be marked complete in the PLAN.md.

Please fell free to ask questions and make recommendations to improve.






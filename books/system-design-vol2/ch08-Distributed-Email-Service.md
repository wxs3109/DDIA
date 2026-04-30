# Chapter 8. Distributed Email Service

## Chapter 8. Distributed Email Service

---

In this chapter we design a large-scale email service, such as Gmail, Outlook, or Yahoo Mail. The growth of the internet has led to an explosion in the volume of emails. In 2020, Gmail had over 1.8 billion active users and Outlook had over 400 million users worldwide [1] [2].

<figure>
<img src="images/ch08-fig01-popular-email-providers.jpg" alt="" width="600">
<figcaption><em>Figure 1 Popular email providers</em></figcaption>
</figure>

## Step 1 - Understand the Problem and Establish Design Scope

Over the years, email services have changed significantly in complexity and scale. A modern email service is a complex system with many functions. There is no way we can design a real-world system in 45 minutes. So before jumping into the design, we definitely want to ask clarifying questions to narrow down the scope.

Candidate: How many people use the product?

Interviewer: One billion users.

Candidate: I think the following features are important:
- Authentication.
- Send and receive emails.
- Fetch all emails.
- Filter emails by read and unread status.
- Search emails by subject, sender, and body.
- Anti-spam and anti-virus.

Are there any other features you would like me to focus on?

Interviewer: That’s a good list. We don’t need to worry about authentication. Let’s focus on the other features you mentioned.

Candidate: How do users connect with mail servers?

Interviewer: Traditionally, users connect with mail servers through native clients that use SMTP, POP, IMAP, and vendor-specific protocols. Those protocols are legacy to some extent, yet still very popular. For this interview, let’s assume HTTP is used for client and server communication.

Candidate: Can emails have attachments?

Interviewer: Yes.

## Non-functional requirements

Next, let’s go over the most important non-functional requirements.

Reliability. We should not lose email data.

Availability. Email and user data should be automatically replicated across multiple nodes to ensure availability. Besides, the system should continue to function despite partial system failures.

Scalability. As the number of users grows, the system should be able to handle the increasing number of users and emails. The performance of the system should not degrade with more users or emails.

Flexibility and extensibility. A flexible/extensible system allows us to add new features or improve performance easily by adding new components. Traditional email protocols such as POP and IMAP have very limited functionality (more on this in high-level design). Therefore, we may need custom protocols to satisfy the flexibility and extensibility requirements.

## Back-of-the-envelope estimation

Let’s do a back-of-the-envelope calculation to determine the scale and to discover some challenges our solution will need to address. By design, emails are storage heavy applications.
- 1 billion users.
- Assume the average number of emails a person sends per day is 10. QPS for sending emails = 109 x 10 / (105) = 100,000.
- Assume the average number of emails a person receives in a day is 40 [3] and the average size of email metadata is 50KB. Metadata refers to everything related to an email, excluding attachment files.
- Assume metadata is stored in a database. Storage requirement for maintaining metadata in 1 year: 1 billion users x 40 emails / day x 365 days x 50 KB = 730 PB.
- Assume 20% of emails contain an attachment and the average attachment size is 500 KB.
- Storage for attachments in 1 year is: 1 billion users x 40 emails / day x 365 days x 20% x 500 KB = 1,460 PB

From this back-of-the-envelope calculation, it’s clear we would deal with a lot of data. So, it’s likely that we need a distributed database solution.

## Step 2 - Propose High-Level Design and Get Buy-In

In this section, we first discuss some basics about email servers and how email servers evolve over time. Then we look at the high-level design of distributed email servers. The content is structured as follows:
- Email knowledge 101
- Traditional mail servers
- Distributed mail servers

## Email knowledge 101

There are various email protocols that are used to send and receive emails. Historically, most mail servers use email protocols such as POP, IMAP, and SMTP.

## Email protocols

SMTP: Simple Mail Transfer Protocol (SMTP) is the standard protocol for sending emails from one mail server to another.

The most popular protocols for retrieving emails are known as Post Office Protocol (POP) and the Internet Mail Access Protocol (IMAP).

POP is a standard mail protocol to receive and download emails from a remote mail server to a local email client. Once emails are downloaded to your computer or phone, they are deleted from the email server, which means you can only access emails on one computer or phone. The details of POP are covered in RFC 1939 [4]. POP requires mail clients to download the entire email. This can take a long time if an email contains a large attachment.

IMAP is also a standard mail protocol for receiving emails for a local email client. When you read an email, you are connected to an external mail server, and data is transferred to your local device. IMAP only downloads a message when you click it, and emails are not deleted from mail servers, meaning that you can access emails from multiple devices. IMAP is the most widely used protocol for individual email accounts. It works well when the connection is slow because only the email header information is downloaded until opened.

HTTPS is not technically a mail protocol, but it can be used to access your mailbox, particularly for web-based email. For example, it’s common for Microsoft Outlook to talk to mobile devices over HTTPS, on a custom-made protocol called ActiveSync [5].

## Domain name service (DNS)

A DNS server is used to look up the mail exchanger record (MX record) for the recipient’s domain. If you run DNS lookup for gmail.com from the command line, you may get MX records as shown in Figure 2.

<figure>
<img src="images/ch08-fig02-mx-records.jpg" alt="A screenshot of a computer  Description automatically generated" width="600">
<figcaption><em>Figure 2 MX records</em></figcaption>
</figure>

The priority numbers indicate preferences, where the mail server with a lower priority number is more preferred. In Figure 2, gmail-smtp-in.l.google.com is used first (priority 5). A sending mail server will attempt to connect and send messages to this mail server first. If the connection fails, the sending mail server will attempt to connect to the mail server with the next lowest priority, which is alt1.gmail-smtp-in.l.google.com (priority 10).

## Attachment

An email attachment is sent along with an email message, commonly with Base64 encoding [6]. There is usually a size limit for an email attachment. For example, Outlook and Gmail limit the size of attachments to 20MB and 25MB respectively as of June 2021. This number is highly configurable and varies from individual to corporate accounts. Multipurpose Internet Mail Extension (MIME) [7] is a specification that allows the attachment to be sent over the internet.

## Traditional mail servers

Before we dive into distributed mail servers, let’s dig a little bit through the history and see how traditional mail servers work, as doing so provides good lessons about how to scale an email server system. You can consider a traditional mail server as a system that works when there are limited email users, usually on a single server.

## Traditional mail server architecture

*Figure 3 describes what happens when Alice sends an email to Bob, using traditional email servers.*

<figure>
<img src="images/ch08-fig03-traditional-mail-servers.jpg" alt="A diagram of a mail server  Description automatically generated" width="600">
<figcaption><em>Figure 3 Traditional mail servers</em></figcaption>
</figure>

The process consists of 4 steps:
1. Alice logs in to her Outlook client, composes an email, and presses “send”. The email is sent to the Outlook mail server. The communication protocol between the Outlook client and mail server is SMTP.
2. Outlook mail server queries the DNS (not shown in the diagram) to find the address of the recipient’s SMTP server. In this case, it is Gmail’s SMTP server. Next, it transfers the email to the Gmail mail server. The communication protocol between the mail servers is SMTP.
3. The Gmail server stores the email and makes it available to Bob, the recipient.
4. Gmail client fetches new emails through the IMAP/POP server when Bob logs in to Gmail.

## Storage

Most email systems at large scale such as Gmail, Outlook, and Yahoo use highly customized databases. In the past, emails were stored in local file directories and each email was stored in a separate file with a unique name. Each user maintained a user directory to store configuration data and mailboxes. Maildir was a popular way to store email messages on the mail server (Figure 4).

<figure>
<img src="images/ch08-fig04-maildir.jpg" alt="A computer screen shot of a computer network  Description automatically generated" width="600">
<figcaption><em>Figure 4 Maildir</em></figcaption>
</figure>

File directories worked well when the user base was small, but it was challenging to retrieve and backup billions of emails. As the email volume grew and the file structure became more complex, disk I/O became a bottleneck. The local directories also don’t satisfy our high availability and reliability requirements. The disk can be damaged and servers can go down. We need a more reliable distributed storage layer.

Email functionality has come a long way since it was invented in the 1960s, from text-based format to rich features such as multimedia, threading [8], search, labels, and more. But email protocols (POP, IMAP, and SMTP) were invented a long time ago and they were not designed to support these new features, nor were they scalable to support billions of users.

## Distributed mail servers

Distributed mail servers are designed to support modern use cases and solve the problems of scale and resiliency. This section covers email APIs, distributed email server architecture, email sending, and email receiving flows.

## Email APIs

Email APIs can mean very different things for different mail clients, or at different stages of an email’s life cycle. For example;
- SMTP/POP/IMAP APIs for native mobile clients.
- SMTP communications between sender and receiver mail servers.
- RESTful API over HTTP for full-featured and interactive web-based email applications.

Due to the length limitations of this book, we cover only some of the most important APIs for webmail. A common way for webmail to communicate is through the HTTP protocol.

1. Endpoint: POST /v1/messages

Sends a message to the recipients in the To, Cc, and Bcc headers.

2. Endpoint: GET /v1/folders

Returns all folders of an email account.

Response:

[{id: string            Unique folder identifier.
  name: string      Name of the folder.
                            According to RFC6154 [9], the default folders can be one of the following:
                            All, Archive, Drafts, Flagged, Junk, Sent, and Trash.
 user_id: string    Reference to the account owner
}]

3. Endpoint: GET /v1/folders/{folder_id}/messages

Returns all messages under a folder. Keep in mind this is a highly simplified API. In reality, this needs to support consecutive paging i.e. 1-50, 51-100, and range-based paging i.e. 73-87, for random access from the last checkpoint.

Response:

List of message objects.

4. Endpoint: GET /v1/messages/{message_id}

Gets all information about a specific message. Messages are core building blocks for an email application, containing information about the sender, recipients, message subject, body, attachments, etc.

Response:

A message’s object.

{

user_id: string              // Reference to the account owner.

from: {name: string, email: string} // <name, email> pair of the sender.

to: [{name: string, email: string}] // A list of <name, email> paris

subject: string // Subject of an email

body: string // Message body

is_read: boolean // Indicate if a message is read or not.

}

## Distributed mail server architecture

While it is easy to set up an email server that handles a small number of users, it is difficult to scale beyond one server. This is mainly because traditional email servers were designed to work with a single server only. Synchronizing data across servers can be difficult, and creating a large-scale email service that doesn’t get marked as spam is very challenging. In this section, we explore how to leverage cloud technologies to make it easier to build distributed mail servers. The high-level design is shown in Figure 5.

<figure>
<img src="images/ch08-fig05-high-level-design.jpg" alt="A diagram of a web server  Description automatically generated" width="600">
<figcaption><em>Figure 5 High-level design</em></figcaption>
</figure>

Let us take a close look at each component.

Webmail. Users use web browsers to receive and send emails.

Web servers. Web servers are public-facing request/response services, used to manage features such as login, signup, user profile, etc. In our design, all email API requests, such as sending an email, loading mail folders, loading all mails in a folder, etc., go through web servers.

Real-time servers. Real-time servers are responsible for pushing new email updates to clients in real-time. Real-time servers are stateful servers because they need to maintain persistent connections. To support real-time communication we have a few options, such as long polling and WebSocket. WebSocket is a more elegant solution, but one drawback of it is browser compatibility. A possible solution is to establish a WebSocket connection whenever possible and to use long-polling as a fallback.

Here is an example of a real-world mail server (Apache James [10]) that implements the JSON Meta Application Protocol (JMAP) subprotocol over WebSocket [11].

Metadata database. This database stores mail metadata including mail subject, body, from user, to users, etc. We discuss the database choice in the deep dive section.

Attachment store. We choose object stores such as Amazon Simple Storage Service (S3) as the attachment store. S3 is a scalable storage infrastructure that’s suitable for storing large files such as images, videos, files, etc. Attachments can take up to 25MB in size. NoSQL column-family databases like Cassandra might not be a good fit for the following two reasons:
- Even though Cassandra supports blob data type and its maximum theoretical size for a blob is 2GB, the practical limit is less than 1MB [12].
- Another problem with putting attachments in Cassandra is that we can’t use a row cache as attachments take too much memory space.

Distributed cache. Since the most recent emails are repeatedly loaded by a client, caching recent emails in memory significantly improves the load time. We can use Redis here because it offers rich features such as lists and it is easy to scale.

Search store. The search store is a distributed document store. It uses a data structure called inverted index [13] that supports very fast full-text searches. We will discuss this in more detail in the deep dive section.

Now that we have discussed some of the most important components to build distributed mail servers, let’s assemble together two main workflows.
- Email sending flow.
- Email receiving flow.

## Email sending flow

The email sending flow is shown in Figure 6.

<figure>
<img src="images/ch08-fig06-email-sending-flow.jpg" alt="A diagram of a computer  Description automatically generated" width="600">
<figcaption><em>Figure 6 Email sending flow</em></figcaption>
</figure>

1. A user writes an email on webmail and presses the “send” button. The request is sent to the load balancer.
2. The load balancer makes sure it doesn’t exceed the rate limit and routes traffic to web servers.
3. Web servers are responsible for:

- Basic email validation. Each incoming email is checked against pre-defined rules such as email size limit.
- Checking if the domain of the recipient’s email address is the same as the sender. If it is the same, email data is inserted to storage, cache, and object store directly. The recipient can fetch the email directly via the RESTful API. There is no need to go to step 4.

1. Message queues.

- If basic email validation succeeds, the email data is passed to the outgoing queue.
- If basic email validation fails, the email is put in the error queue.

1. SMTP outgoing workers pull events from the outgoing queue and make sure emails are spam and virus free.
2. The outgoing email is stored in the “Sent Folder” of the storage layer.
3. SMTP outgoing workers send the email to the recipient mail server.

Each message in the outgoing queue contains all the metadata required to create an email. A distributed message queue is a critical component that allows asynchronous mail processing. By decoupling SMTP outgoing workers from the web servers, we can scale SMTP outgoing workers independently.

We monitor the size of the outgoing queue very closely. If there are many emails stuck in the queue, we need to analyze the cause of the issue. Here are some possibilities:
- The recipient’s mail server is unavailable. In this case, we need to retry sending the email at a later time. Exponential backoff [14] might be a good retry strategy.
- Not enough consumers to send emails. In this case, we may need more consumers to reduce the processing time.

## Email receiving flow

The following diagram demonstrates the email receiving flow.

<figure>
<img src="images/ch08-fig07-email-receiving-flow.jpg" alt="A diagram of a diagram  Description automatically generated" width="600">
<figcaption><em>Figure 7 Email receiving flow</em></figcaption>
</figure>

1. Incoming emails arrive at the SMTP load balancer.
2. The load balancer distributes traffic among SMTP servers. Email acceptance policy can be configured and applied at the SMTP-connection level. For example, invalid emails are bounced to avoid unnecessary email processing.
3. If the attachment of an email is too large to put into the queue, we can put it into the attachment store (s3).
4. Emails are put in the incoming email queue. The queue decouples mail processing workers from SMTP servers so they can be scaled independently. Moreover, the queue serves as a buffer in case the email volume surges.
5. Mail processing workers are responsible for a lot of tasks, including filtering out spam mails, stopping viruses, etc. The following steps assume an email passed the validation.
6. The email is stored in the mail storage, cache, and object data store.
7. If the receiver is currently online, the email is pushed to real-time servers.
8. Real-time servers are WebSocket servers that allow clients to receive new emails in real-time.
9. For offline users, emails are stored in the storage layer. When a user comes back online, the webmail client connects to web servers via RESTful API.
10. Web servers pull new emails from the storage layer and return them to the client.

## Step 3 - Design Deep Dive

Now that we have talked about all the parts of the email server, let’s go deeper into some key components and examine how to scale the system.
- Metadata database
- Search
- Deliverability
- Scalability

## Metadata database

In this section, we discuss the characteristics of email metadata, choosing the right database, data model, and conversation threads (bonus point).

## Characteristics of email metadata

- Email headers are usually small and frequently accessed.
- Email body sizes can range from small to big but are infrequently accessed. You normally only read an email once.
- Most of the mail operations, such as fetching mails, marking an email as read, and searching are isolated to an individual user. In other words, mails owned by a user are only accessible by that user and all the mail operations are performed by the same user.
- Data recency impacts data usage. Users usually only read the most recent emails. 82% of read queries are for data younger than 16 days [15].
- Data has high-reliability requirements. Data loss is not acceptable.

## Choosing the right database

At the Gmail or Outlook scale, the database system is usually custom-made to reduce input/output operations per second (IOPS) [16], as this can easily become a major constraint in the system. Choosing the right database is not easy. It is helpful to consider all the options we have on the table before deciding the most suitable one.
- Relational database. The main motivation behind this is to search through emails efficiently. We can build indexes for email header and body. With indexes, simple search queries are fast. However, relational databases are typically optimized for small chunks of data entries and are not ideal for large ones. A typical email is usually larger than a few KB and can easily be over 100KB when HTML is involved. You might argue that the BLOB data type is designed to support large data entries. However, search queries over unstructured BLOB data type are not efficient. So MySQL or PostgreSQL are not good fits.
- Distributed object storage. Another potential solution is to store raw emails in cloud storage such as Amazon S3, which can be a good option for backup storage, but it’s hard to efficiently support features such as marking emails as read, searching emails based on keywords, threading emails, etc.
- NoSQL databases. Google Bigtable is used by Gmail, so it’s definitely a viable solution. However, Bigtable is not open sourced and how email search is implemented remains a mystery. Cassandra might be a good option as well, but we haven’t seen any large email providers use it yet.

Based on the above analysis, very few existing solutions seem to fit our needs perfectly. Large email service providers tend to have their own highly customized databases. If you build a brand new mail server, you might think about a custom-made KV store. However, in an interview setting, we won’t have time to design a new distributed database, but it’s important to explain the following characteristics that the database should have.
- A single column can be a single-digit of MB.
- Strong data consistency.
- Designed to reduce disk I/O.
- It should be highly available and fault-tolerant.
- It should be easy to create incremental backups.

## Data model

One way to store the data is to use user_id as a partition key so data for one user is stored on a single shard. One potential limitation with this data model is that messages are not shared among multiple users. Since this is not a requirement for us in this interview, it’s not something we need to worry about.

Now let us define the tables. The primary key contains two components, the partition key, and the clustering key.
- Partition key: responsible for distributing data across nodes. As a general rule, we want to spread the data evenly.
- Clustering key: responsible for sorting data within a partition.

At a high level, an email service needs to support the following queries at the data layer:
- The first query is to get all folders for a user.
- The second query is to display all emails for a specific folder.
- The third query is to create/delete/get a specific email.
- The fourth query is to fetch all read or unread emails.
- Bonus point: get conversation threads.

Let’s take a look at them one by one.

Query 1: get all folders for a user.

As shown in Table 1, user_id is the partition key, so folders owned by the same user are located in one partition.

<figure>
<img src="images/ch08-tbl01-folders-by-user.jpg" alt="A screenshot of a computer  Description automatically generated" width="600">
<figcaption><em>Table 1 Folders by user</em></figcaption>
</figure>

When a user loads their inbox, emails are usually sorted by timestamp, showing the most recent at the top. In order to store all emails for the same folder in one partition, composite partition key <user_id, folder_id> is used. Another column to note is email_id. Its data type is TIMEUUID [17], and it is the clustering key used to sort emails in chronological order.

<figure>
<img src="images/ch08-tbl02-emails-by-folder.jpg" alt="A close-up of a computer screen  Description automatically generated" width="600">
<figcaption><em>Table 2 Emails by folder</em></figcaption>
</figure>

Query 3: create/delete/get an email

Due to space limitations, we only explain how to get detailed information about an email. The two tables in Table 3 are designed to support this query. The simple query looks like this:

```
SELECT * FROM emails_by_user WHERE email_id = 123;
```

An email can have multiple attachments, and these can be retrieved by the combination of email_id and filename fields.

<figure>
<img src="images/ch08-tbl03-emails-by-user.jpg" alt="A close-up of a computer screen  Description automatically generated" width="600">
<figcaption><em>Table 3 Emails by user</em></figcaption>
</figure>

Query 4: fetch all read or unread emails

If our domain model was for a relational database, the query to fetch all read emails would look like this:

| SELECT * FROM emails_by_folder WHERE user_id = <user_id> and folder_id = <folder_id> and is_read = trueORDERBY email_id; |
|---|

The query to fetch all unread emails would look very similar. We just need to change ‘is_read = true ’ to ‘is_read = false ’ in the above query.

Our data model, however, is designed for NoSQL. A NoSQL database normally only supports queries on partition and cluster keys. Since is_read in the emails_by_folder table is neither of those, most NoSQL databases will reject this query.

One way to get around this limitation is to fetch the entire folder for a user and perform the filtering in the application. This could work for a small email service, but at our design scale this does not work well.

This problem is commonly solved with denormalization in NoSQL. To support the read/unread queries, we denormalize the emails_by_folder data into two tables as shown in Table 4.

<figure>
<img src="images/ch08-tbl04-read-and-unread-emails.jpg" alt="A close-up of a computer screen  Description automatically generated" width="600">
</figure>